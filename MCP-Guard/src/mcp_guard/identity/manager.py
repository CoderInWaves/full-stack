"""Agent Identity Manager — verifies and manages agent identities."""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from typing import Optional

from mcp_guard.core.constants import (
    REASON_DISABLED_AGENT,
    REASON_INVALID_TOKEN,
    REASON_MISSING_IDENTITY,
    REASON_UNKNOWN_AGENT,
)
from mcp_guard.core.exceptions import AuthenticationError
from mcp_guard.core.models import AgentIdentity, GatewayConfig, IdentityContext

logger = logging.getLogger("mcp_guard.identity")


class IdentityManager:
    """Manages agent identities and authentication.

    For STDIO: Identity is bound to the trusted process configuration.
    For HTTP: Identity is verified via token-to-agent mapping.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self._agents: dict[str, AgentIdentity] = {}
        self._token_map: list[tuple[str, IdentityContext, bool]] = []
        self._admin_token_map: list[tuple[str, str, bool, list[str]]] = []
        self._jwt_config = config.identity.jwt
        self._revoked_token_hashes: set[str] = set()
        self._revoked_jti: set[str] = set()
        self._revocation_lock = threading.RLock()

        # Load agents from config
        for _key, agent in config.identity.agents.items():
            self._agents[agent.id] = agent
            if agent.api_key_hash:
                self._token_map.append(
                    (
                        self._normalize_hash(agent.api_key_hash),
                        self._context_from_agent(agent),
                        True,
                    )
                )

        # Additional credentials allow one agent to act for configured users
        # and tenants without accepting those values from MCP request arguments.
        for credential in config.identity.credentials.values():
            agent_record = self._agents.get(credential.agent_id)
            base_context = (
                self._context_from_agent(agent_record)
                if agent_record
                else IdentityContext(agent_id=credential.agent_id)
            )
            context = IdentityContext(
                agent_id=credential.agent_id,
                tenant_id=(
                    credential.tenant_id
                    if credential.tenant_id is not None
                    else base_context.tenant_id
                ),
                user_id=(
                    credential.user_id if credential.user_id is not None else base_context.user_id
                ),
                roles=credential.roles if credential.roles is not None else base_context.roles,
            )
            self._token_map.append(
                (
                    self._normalize_hash(credential.api_key_hash),
                    context,
                    credential.enabled,
                )
            )

        for admin_credential in config.identity.admin_credentials.values():
            self._admin_token_map.append(
                (
                    self._normalize_hash(admin_credential.api_key_hash),
                    admin_credential.id,
                    admin_credential.enabled,
                    list(admin_credential.roles),
                )
            )

        # For STDIO, the agent_id comes from config directly
        self._stdio_agent_id = config.identity.agent_id

    def get_stdio_agent_id(self) -> str:
        """Get the agent ID for STDIO transport (from trusted config)."""
        if not self._stdio_agent_id:
            raise AuthenticationError(REASON_MISSING_IDENTITY)
        return self._stdio_agent_id

    def verify_stdio_agent(self) -> AgentIdentity:
        """Verify and return the STDIO agent identity."""
        agent_id = self.get_stdio_agent_id()
        return self._get_verified_agent(agent_id)

    def verify_http_agent(self, token: str) -> AgentIdentity:
        """Verify an HTTP client's token and return the agent identity.

        Args:
            token: The bearer token from the HTTP request.

        Returns:
            Verified AgentIdentity.

        Raises:
            AuthenticationError: If the token is invalid or agent is not found/disabled.
        """
        context = self.verify_http_context(token)
        return self._get_verified_agent(context.agent_id)

    def verify_http_context(self, token: str) -> IdentityContext:
        """Verify a bearer credential and return its trusted identity context."""
        if not token:
            raise AuthenticationError(REASON_MISSING_IDENTITY)

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._revocation_lock:
            if token_hash in self._revoked_token_hashes:
                raise AuthenticationError(REASON_INVALID_TOKEN)
        matched_context: Optional[IdentityContext] = None
        matched_enabled = True
        with self._revocation_lock:
            for stored_hash, context, credential_enabled in self._token_map:
                if hmac.compare_digest(token_hash, stored_hash):
                    matched_context = context
                    matched_enabled = credential_enabled
        if matched_context is None:
            if self._jwt_config and self._jwt_config.enabled:
                return self._verify_jwt(token)
            logger.warning("Invalid authentication token received")
            raise AuthenticationError(REASON_INVALID_TOKEN)
        if not matched_enabled:
            raise AuthenticationError(REASON_DISABLED_AGENT)

        self._get_verified_agent(matched_context.agent_id)
        return matched_context

    def revoke_token_hash(self, value: str) -> None:
        """Revoke a configured SHA-256 bearer token until process restart."""
        digest = self._normalize_hash(value)
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("token_hash must be a SHA-256 hex digest")
        with self._revocation_lock:
            self._revoked_token_hashes.add(digest)

    def rotate_token_hash(self, old_value: str, new_value: str) -> None:
        """Replace an agent token hash while preserving its trusted identity mapping."""
        old_hash = self._normalize_hash(old_value)
        new_hash = self._normalize_hash(new_value)
        for digest in (old_hash, new_hash):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("token hashes must be SHA-256 hex digests")
        if hmac.compare_digest(old_hash, new_hash):
            raise ValueError("new token hash must differ from old token hash")
        context: Optional[IdentityContext] = None
        enabled = True
        with self._revocation_lock:
            for stored_hash, stored_context, stored_enabled in self._token_map:
                if hmac.compare_digest(stored_hash, old_hash):
                    context = stored_context
                    enabled = stored_enabled
            if context is None:
                raise KeyError("The old token hash is not configured")
            if any(
                hmac.compare_digest(stored_hash, new_hash) for stored_hash, *_ in self._token_map
            ):
                raise ValueError("new token hash is already configured")
            self._revoked_token_hashes.add(old_hash)
            self._token_map.append((new_hash, context, enabled))

    def revoke_jti(self, jti: str) -> None:
        """Revoke an OIDC JWT by its issuer-provided token identifier."""
        if not jti or len(jti) > 512:
            raise ValueError("jti must be a non-empty value of at most 512 characters")
        with self._revocation_lock:
            self._revoked_jti.add(jti)

    def _verify_jwt(self, token: str) -> IdentityContext:
        """Validate a signed JWT against issuer, audience, time, and claim rules."""
        config = self._jwt_config
        assert config is not None and config.enabled
        try:
            import jwt

            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            if (
                not isinstance(algorithm, str)
                or algorithm == "none"
                or algorithm not in config.algorithms
            ):
                raise ValueError("JWT algorithm is not allowed")
            if config.jwks_url:
                signing_key = jwt.PyJWKClient(config.jwks_url).get_signing_key_from_jwt(token).key
            elif config.public_keys:
                kid = header.get("kid")
                if not isinstance(kid, str) or kid not in config.public_keys:
                    raise ValueError("JWT signing key was not found")
                signing_key = config.public_keys[kid]
            elif config.secret:
                signing_key = config.secret
            else:
                raise ValueError("No JWT signing key is configured")

            claims = jwt.decode(
                token,
                signing_key,
                algorithms=config.algorithms,
                issuer=config.issuer,
                audience=config.audience,
                leeway=config.leeway_seconds,
                options={"require": ["exp", "iss", "aud"]},
            )
            agent_id = claims.get(config.agent_claim)
            if not isinstance(agent_id, str) or not agent_id:
                raise ValueError("JWT is missing the configured agent claim")
            agent = self._get_verified_agent(agent_id)
            jti = claims.get("jti")
            if jti is not None:
                with self._revocation_lock:
                    revoked = jti in self._revoked_jti if isinstance(jti, str) else False
                if not isinstance(jti, str) or revoked:
                    raise ValueError("JWT has been revoked")

            scope_value = claims.get(config.scope_claim, "")
            if isinstance(scope_value, str):
                scopes = set(scope_value.split())
            elif isinstance(scope_value, list) and all(
                isinstance(item, str) for item in scope_value
            ):
                scopes = set(scope_value)
            else:
                raise ValueError("JWT scope claim has an invalid type")
            if not set(config.required_scopes).issubset(scopes):
                raise ValueError("JWT is missing a required scope")

            tenant_id = claims.get(config.tenant_claim, agent.tenant_id)
            user_id = claims.get(config.user_claim, agent.user_id)
            roles = claims.get(config.roles_claim, [])
            if not isinstance(tenant_id, str) or not isinstance(user_id, str):
                raise ValueError("JWT tenant or user claim has an invalid type")
            if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
                raise ValueError("JWT roles claim must be a list of strings")
            return IdentityContext(
                agent_id=agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                roles=roles,
            )
        except Exception as exc:
            logger.warning("JWT authentication failed: %s", type(exc).__name__)
            raise AuthenticationError(REASON_INVALID_TOKEN) from exc

    def verify_admin_token(self, token: str) -> tuple[str, list[str]]:
        """Validate an admin-only bearer token; agent tokens never grant admin access."""
        if not token:
            raise AuthenticationError(REASON_MISSING_IDENTITY)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        matched: Optional[tuple[str, bool, list[str]]] = None
        for stored_hash, admin_id, enabled, roles in self._admin_token_map:
            if hmac.compare_digest(token_hash, stored_hash):
                matched = (admin_id, enabled, roles)
        if matched is None or not matched[1] or "admin" not in matched[2]:
            logger.warning("Invalid administrator authentication token received")
            raise AuthenticationError(REASON_INVALID_TOKEN)
        return matched[0], matched[2]

    def _get_verified_agent(self, agent_id: str) -> AgentIdentity:
        """Look up and verify an agent by ID."""
        agent = self._agents.get(agent_id)
        if agent is None:
            logger.warning("Unknown agent attempted access: %s", agent_id)
            raise AuthenticationError(REASON_UNKNOWN_AGENT)

        if not agent.enabled:
            logger.warning("Disabled agent attempted access: %s", agent_id)
            raise AuthenticationError(REASON_DISABLED_AGENT)

        return agent

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        """Get an agent by ID without raising."""
        return self._agents.get(agent_id)

    def get_context_for_agent(self, agent_id: str) -> Optional[IdentityContext]:
        """Return the trusted static identity context for a configured agent."""
        agent = self._agents.get(agent_id)
        return self._context_from_agent(agent) if agent else None

    def is_agent_assigned_to_server(self, agent_id: str, server_name: str) -> bool:
        """Check if an agent is assigned to a specific server."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        # Empty servers list means all servers (for backward compatibility)
        if not agent.servers:
            return True
        return server_name in agent.servers

    def register_token(self, agent_id: str, token: str) -> None:
        """Register a token for an agent (for testing/setup)."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._token_map = [entry for entry in self._token_map if entry[0] != token_hash]
        context = self.get_context_for_agent(agent_id) or IdentityContext(agent_id=agent_id)
        self._token_map.append((token_hash, context, True))
        agent = self._agents.get(agent_id)
        if agent:
            agent.api_key_hash = token_hash

    @staticmethod
    def _context_from_agent(agent: Optional[AgentIdentity]) -> IdentityContext:
        """Build a context from administrator-owned identity configuration."""
        if agent is None:
            return IdentityContext(agent_id="")
        return IdentityContext(
            agent_id=agent.id,
            tenant_id=agent.tenant_id,
            user_id=agent.user_id,
            roles=list(agent.roles),
        )

    @staticmethod
    def _normalize_hash(value: str) -> str:
        """Accept the documented sha256: prefix as well as bare hex digests."""
        digest = value.removeprefix("sha256:").lower()
        return digest
