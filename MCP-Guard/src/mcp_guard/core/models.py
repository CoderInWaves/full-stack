"""Core data models for MCP-Guard using Pydantic."""

from __future__ import annotations

import enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConfigModel(BaseModel):
    """Base model for strict YAML configuration records."""

    model_config = ConfigDict(extra="forbid")


# --- Policy Models ---


class PolicyAction(str, enum.Enum):  # noqa: UP042 -- preserve compatibility with Python 3.9 tooling
    """Actions that a policy rule can specify."""

    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class DLPMode(str, enum.Enum):  # noqa: UP042 -- preserve compatibility with Python 3.9 tooling
    """DLP enforcement modes."""

    BLOCK = "block"
    REDACT = "redact"


class DLPPattern(ConfigModel):
    """A single DLP detection pattern."""

    name: str
    pattern: str  # regex pattern
    mode: DLPMode = DLPMode.REDACT
    replacement: str = "[REDACTED]"
    enabled: bool = True
    agents: list[str] = Field(default_factory=list)
    tenant_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    servers: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)


class ArgumentConstraint(ConfigModel):
    """Constraint for a tool argument using JSON Schema."""

    json_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ToolPolicy(ConfigModel):
    """Policy for a specific tool."""

    action: PolicyAction = PolicyAction.DENY
    argument_constraints: Optional[ArgumentConstraint] = None
    tenant_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    identity_argument_bindings: dict[str, str] = Field(default_factory=dict)


class ServerPolicy(ConfigModel):
    """Policy for an upstream MCP server."""

    enabled: bool = True
    tools: dict[str, ToolPolicy] = Field(default_factory=dict)
    resources: dict[str, ToolPolicy] = Field(default_factory=dict)
    prompts: dict[str, ToolPolicy] = Field(default_factory=dict)
    methods: dict[str, PolicyAction] = Field(default_factory=dict)


class AgentPolicy(ConfigModel):
    """Policy for a specific agent."""

    servers: dict[str, ServerPolicy] = Field(default_factory=dict)
    tenant_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class PolicyConfig(ConfigModel):
    """Top-level policy configuration."""

    default_action: PolicyAction = PolicyAction.DENY
    agents: dict[str, AgentPolicy] = Field(default_factory=dict)


# --- Agent Identity Models ---


class AgentIdentity(ConfigModel):
    """An agent identity record."""

    id: str
    name: str = ""
    enabled: bool = True
    servers: list[str] = Field(default_factory=list)
    api_key_hash: Optional[str] = None  # bcrypt or sha256 hash for HTTP auth
    tenant_id: str = ""
    user_id: str = ""
    roles: list[str] = Field(default_factory=list)
    allowed_tenants: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)


class IdentityCredential(ConfigModel):
    """One HTTP credential mapped to a trusted agent and optional user context."""

    agent_id: str
    api_key_hash: str
    enabled: bool = True
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    roles: Optional[list[str]] = None


class AdminCredential(ConfigModel):
    """Hashed bearer credential with access to MCP-Guard admin endpoints."""

    id: str
    api_key_hash: str
    enabled: bool = True
    roles: list[str] = Field(default_factory=lambda: ["admin"])


class JWTAuthConfig(ConfigModel):
    """Optional OIDC-compatible JWT validation for HTTP bearer credentials."""

    enabled: bool = False
    issuer: str = ""
    audience: str = ""
    jwks_url: Optional[str] = None
    public_keys: dict[str, str] = Field(default_factory=dict)
    secret: Optional[str] = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    required_scopes: list[str] = Field(default_factory=list)
    agent_claim: str = "agent_id"
    tenant_claim: str = "tenant_id"
    user_claim: str = "sub"
    roles_claim: str = "roles"
    scope_claim: str = "scope"
    leeway_seconds: int = Field(default=0, ge=0, le=60)


# --- Configuration Models ---


class UpstreamConfig(ConfigModel):
    """Configuration for an upstream MCP server."""

    name: str
    command: Optional[list[str]] = None  # For STDIO
    url: Optional[str] = None  # For HTTP
    env: dict[str, str] = Field(default_factory=dict)


class STDIOTransportConfig(ConfigModel):
    """STDIO transport configuration."""

    upstream: UpstreamConfig


class RESTActionConfig(ConfigModel):
    """Administrator-pinned upstream REST operation for the action gateway."""

    server_name: str
    url: str
    method: str = "POST"
    upstream_headers: dict[str, str] = Field(default_factory=dict)


class HTTPTransportConfig(ConfigModel):
    """HTTP transport configuration."""

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    upstream_url: str = ""
    allowed_origins: list[str] = Field(default_factory=list)
    upstream_headers: dict[str, str] = Field(default_factory=dict)
    rest_actions: dict[str, RESTActionConfig] = Field(default_factory=dict)
    tls_cert_file: Optional[str] = None
    tls_key_file: Optional[str] = None
    client_ca_file: Optional[str] = None
    require_client_certificate: bool = False


class LoggingConfig(ConfigModel):
    """Logging configuration."""

    format: str = "jsonl"
    level: str = "INFO"
    file: str = "logs/audit.jsonl"
    max_size_mb: int = Field(default=100, gt=0)
    backup_count: int = Field(default=5, ge=1)
    log_arguments: bool = False  # Do not log full arguments by default
    log_responses: bool = False  # Do not log full responses by default


class SecurityConfig(ConfigModel):
    """Security settings."""

    max_message_size: int = Field(default=1048576, gt=0)  # 1MB
    request_timeout_seconds: int = Field(default=30, gt=0)
    approval_timeout_seconds: int = Field(default=900, ge=1, le=86400)
    enable_dlp: bool = True
    dlp_patterns: list[DLPPattern] = Field(default_factory=list)


class IdentityConfig(ConfigModel):
    """Identity configuration for the gateway."""

    agent_id: str = ""
    agents: dict[str, AgentIdentity] = Field(default_factory=dict)
    credentials: dict[str, IdentityCredential] = Field(default_factory=dict)
    admin_credentials: dict[str, AdminCredential] = Field(default_factory=dict)
    jwt: Optional[JWTAuthConfig] = None


class IdentityContext(ConfigModel):
    """Trusted tenant and user context derived from local identity config or auth."""

    agent_id: str
    tenant_id: str = ""
    user_id: str = ""
    roles: list[str] = Field(default_factory=list)


class GatewayConfig(ConfigModel):
    """Full gateway configuration."""

    name: str = "MCP-Guard"
    environment: str = "development"
    transport: str = "stdio"  # "stdio" or "http"
    default_policy: PolicyAction = PolicyAction.DENY

    stdio: Optional[STDIOTransportConfig] = None
    http: Optional[HTTPTransportConfig] = None

    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    upstreams: dict[str, UpstreamConfig] = Field(default_factory=dict)


# --- MCP Protocol Models ---


class JSONRPCMessage(BaseModel):
    """Parsed JSON-RPC message."""

    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[dict[str, Any]] = None

    @property
    def has_id(self) -> bool:
        """Whether the input message explicitly supplied an ID field."""
        return "id" in self.model_fields_set

    @property
    def has_result(self) -> bool:
        """Whether the input message explicitly supplied a result field."""
        return "result" in self.model_fields_set

    @property
    def has_error(self) -> bool:
        """Whether the input message explicitly supplied an error field."""
        return "error" in self.model_fields_set

    @property
    def is_request(self) -> bool:
        return self.method is not None and self.has_id

    @property
    def is_notification(self) -> bool:
        return self.method is not None and not self.has_id

    @property
    def is_response(self) -> bool:
        return self.method is None and self.has_id

    @property
    def is_error(self) -> bool:
        return self.error is not None


class ToolCallInfo(BaseModel):
    """Extracted information from a tools/call request."""

    request_id: Any
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    server_name: str = ""
    agent_id: str = ""
    tenant_id: str = ""
    user_id: str = ""
    roles: list[str] = Field(default_factory=list)
    identity_context: Optional[IdentityContext] = None


class SecurityDecision(BaseModel):
    """Result of a security policy evaluation."""

    allowed: bool
    decision: str  # ALLOW, DENY, REDACT, APPROVAL_REQUIRED
    reason_code: str = ""
    reason_message: str = ""
    agent_id: str = ""
    server_name: str = ""
    tool_name: str = ""
    tenant_id: str = ""
    user_id: str = ""
    latency_ms: float = 0.0


class AuditEvent(ConfigModel):
    """An audit log entry."""

    timestamp: str
    agent_id: str = ""
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    server: str = ""
    method: str = ""
    tool: str = ""
    resource: Optional[str] = None
    prompt: Optional[str] = None
    correlation_id: Optional[str] = None
    decision: str = ""
    reason_code: str = ""
    request_id: Optional[Any] = None
    latency_ms: float = 0.0
    error: Optional[str] = None
    dlp_findings: Optional[list[str]] = None
    arguments: Optional[dict[str, Any]] = None
    response: Optional[Any] = None
