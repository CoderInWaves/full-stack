"""Data Loss Prevention Engine — deterministic pattern-based DLP."""

from __future__ import annotations

import json
import logging
import re as stdlib_re
import sys
from typing import Any, cast

try:
    import regex as regex_engine

    _REGEX_TIMEOUT_SUPPORTED = True
except ImportError:  # Compatibility only for source-tree checks on unsupported Python.
    regex_engine = stdlib_re
    _REGEX_TIMEOUT_SUPPORTED = False

from mcp_guard.core.exceptions import ConfigurationError, DLPViolationError
from mcp_guard.core.models import DLPMode, DLPPattern, GatewayConfig, IdentityContext

logger = logging.getLogger("mcp_guard.dlp")
PYTHON_REQUIRES_TIMEOUT_REGEX = sys.version_info >= (3, 11)

# Maximum input size for DLP scanning (10 MB)
MAX_DLP_INPUT_SIZE = 10 * 1024 * 1024

# Maximum pattern complexity (limit repetition)
MAX_PATTERN_LENGTH = 500
DLP_REGEX_TIMEOUT_SECONDS = 0.1


def is_safe_pattern(pattern: str) -> bool:
    """Reject common catastrophic-backtracking shapes before compiling regexes.

    Python's standard regex engine has no per-match timeout. This conservative
    scanner rejects unbounded repetition around a group that itself contains
    unbounded repetition or alternation, and rejects very large explicit
    repeat bounds. Input and pattern length limits provide a second bound.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        return False

    groups: list[dict[str, bool]] = [{"unbounded": False, "alternation": False}]
    in_character_class = False
    escaped = False
    index = 0

    while index < len(pattern):
        char = pattern[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char == "[":
            in_character_class = True
            index += 1
            continue
        if char == "]" and in_character_class:
            in_character_class = False
            index += 1
            continue
        if in_character_class:
            index += 1
            continue

        if char == "(":
            groups.append({"unbounded": False, "alternation": False})
            index += 1
            continue
        if char == "|":
            groups[-1]["alternation"] = True
            index += 1
            continue
        if char == ")" and len(groups) > 1:
            group = groups.pop()
            next_index = index + 1
            if next_index < len(pattern) and pattern[next_index] in "*+{":
                if group["unbounded"] or group["alternation"]:
                    return False
                if pattern[next_index] == "{":
                    end_index = pattern.find("}", next_index + 1)
                    if end_index == -1:
                        return False
                    bound = pattern[next_index + 1 : end_index]
                    if "," in bound:
                        lower, _, upper = bound.partition(",")
                        if lower.isdigit() and int(lower) > 1000:
                            return False
                        if upper.isdigit() and int(upper) > 1000:
                            return False
                        if upper == "":
                            groups[-1]["unbounded"] = True
                    elif bound.isdigit() and int(bound) > 1000:
                        return False
                else:
                    groups[-1]["unbounded"] = True
            groups[-1]["unbounded"] = groups[-1]["unbounded"] or group["unbounded"]
            groups[-1]["alternation"] = groups[-1]["alternation"] or group["alternation"]
            index += 1
            continue

        if char in "*+":
            groups[-1]["unbounded"] = True
        elif char == "{":
            end_index = pattern.find("}", index + 1)
            if end_index == -1:
                return False
            bound = pattern[index + 1 : end_index]
            if "," in bound:
                lower, _, upper = bound.partition(",")
                if lower.isdigit() and int(lower) > 1000:
                    return False
                if upper.isdigit() and int(upper) > 1000:
                    return False
                if upper == "":
                    groups[-1]["unbounded"] = True
            elif bound.isdigit() and int(bound) > 1000:
                return False
        index += 1

    return len(groups) == 1 and not in_character_class and not escaped


class DLPEngine:
    """Deterministic Data Loss Prevention engine.

    Scans text content for configured sensitive patterns and either
    redacts or blocks based on policy.

    LIMITATION: This is regex-based detection. It does not claim to
    identify every possible secret or sensitive data leak.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.enabled = config.security.enable_dlp
        self._compiled_patterns: list[tuple[DLPPattern, Any]] = []

        if self.enabled:
            if PYTHON_REQUIRES_TIMEOUT_REGEX and not _REGEX_TIMEOUT_SUPPORTED:
                raise ConfigurationError(
                    "The regex dependency is required on Python 3.11+ for bounded DLP matching."
                )
            for pat in config.security.dlp_patterns:
                if not pat.enabled:
                    continue
                if not is_safe_pattern(pat.pattern):
                    logger.warning(
                        "DLP pattern '%s' is too complex or exceeds max length (%d), skipping",
                        pat.name,
                        MAX_PATTERN_LENGTH,
                    )
                    continue
                try:
                    compiled = regex_engine.compile(pat.pattern, regex_engine.IGNORECASE)
                    self._compiled_patterns.append((pat, compiled))
                except regex_engine.error as e:
                    logger.error("Invalid DLP regex '%s': %s", pat.name, e)

    def inspect_message(
        self,
        raw: str,
        agent_id: str = "",
        server_name: str = "",
        direction: str = "response",
        method: str = "",
        context: IdentityContext | None = None,
    ) -> str:
        """Inspect a message for sensitive data patterns.

        Args:
            raw: The raw message string.
            agent_id: The agent identity.
            server_name: The upstream server.
            direction: "request" or "response".
            method: MCP method for this request/response pair.

        Returns:
            The (possibly redacted) message string.

        Raises:
            DLPViolationError: If a BLOCK pattern matches.
        """
        if not self.enabled:
            return raw

        if len(raw) > MAX_DLP_INPUT_SIZE:
            raise DLPViolationError(
                pattern_name="DLP_INPUT_TOO_LARGE",
                message="DLP inspection limit exceeded",
            )
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return self._inspect_text(
                raw,
                agent_id,
                server_name,
                direction,
                method,
                context.tenant_id if context else "",
                context.user_id if context else "",
            )

        targets = self._text_targets(message, direction, method)
        changed = False
        for target in targets:
            inspected = self._inspect_text(
                target[0],
                agent_id,
                server_name,
                direction,
                method,
                context.tenant_id if context else "",
                context.user_id if context else "",
            )
            if inspected != target[0]:
                target[1](inspected)
                changed = True

        if not changed:
            return raw
        return json.dumps(message, separators=(",", ":"), ensure_ascii=False)

    def _inspect_text(
        self,
        text: str,
        agent_id: str,
        server_name: str,
        direction: str,
        method: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> str:
        """Apply patterns to one relevant text value."""
        result = text
        for pat, compiled in self._compiled_patterns:
            if pat.agents and agent_id not in pat.agents:
                continue
            if pat.tenant_ids and tenant_id not in pat.tenant_ids:
                continue
            if pat.user_ids and user_id not in pat.user_ids:
                continue
            if pat.servers and server_name not in pat.servers:
                continue
            if pat.methods and method not in pat.methods:
                continue
            if pat.directions and direction not in pat.directions:
                continue
            matches = _findall(compiled, result)
            if not matches:
                continue
            logger.info(
                "DLP match: pattern=%s direction=%s agent=%s server=%s count=%d",
                pat.name,
                direction,
                agent_id,
                server_name,
                len(matches),
            )
            if pat.mode == DLPMode.BLOCK:
                raise DLPViolationError(
                    pattern_name=pat.name,
                    message=f"DLP policy blocks {direction}: matched pattern '{pat.name}'",
                )
            result = _sub(compiled, pat.replacement, result)
        return result

    def _text_targets(self, message: Any, direction: str, method: str) -> list[tuple[str, Any]]:
        """Return mutable text values to inspect without touching protocol metadata."""
        targets: list[tuple[str, Any]] = []

        def add_mapping_values(value: Any, setter: Any) -> None:
            if isinstance(value, str):
                targets.append((value, setter))
            elif isinstance(value, dict):
                for key, nested in value.items():
                    if isinstance(key, str) and key != "_meta":
                        add_mapping_values(
                            nested, lambda updated, obj=value, k=key: obj.__setitem__(k, updated)
                        )
            elif isinstance(value, list):
                for position, nested in enumerate(value):
                    add_mapping_values(
                        nested, lambda updated, obj=value, i=position: obj.__setitem__(i, updated)
                    )

        if isinstance(message, dict) and message.get("method") in {"tools/call", "prompts/get"}:
            params = message.get("params")
            if isinstance(params, dict):
                arguments = params.get("arguments")
                add_mapping_values(
                    arguments,
                    lambda updated, obj=params: obj.__setitem__("arguments", updated),
                )
            return targets

        if isinstance(message, dict) and message.get("method") == "tasks/update":
            params = message.get("params")
            if isinstance(params, dict) and "inputResponses" in params:
                add_mapping_values(
                    params["inputResponses"],
                    lambda updated, obj=params: obj.__setitem__("inputResponses", updated),
                )
            return targets

        if isinstance(message, dict) and "result" in message:
            result = message.get("result")
            if isinstance(result, dict):
                content = result.get("content")
                if isinstance(content, list):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "text"
                            and isinstance(block.get("text"), str)
                        ):
                            targets.append(
                                (
                                    block["text"],
                                    lambda updated, obj=block: obj.__setitem__("text", updated),
                                )
                            )
                if method == "resources/read":
                    contents = result.get("contents")
                    if isinstance(contents, list):
                        for item in contents:
                            if isinstance(item, dict) and isinstance(item.get("text"), str):
                                targets.append(
                                    (
                                        item["text"],
                                        lambda updated, obj=item: obj.__setitem__("text", updated),
                                    )
                                )
                elif method == "prompts/get":
                    messages = result.get("messages")
                    if isinstance(messages, list):
                        for prompt_message in messages:
                            if not isinstance(prompt_message, dict):
                                continue
                            prompt_content = prompt_message.get("content")
                            if isinstance(prompt_content, dict):
                                prompt_content = [prompt_content]
                            if isinstance(prompt_content, list):
                                for block in prompt_content:
                                    if (
                                        isinstance(block, dict)
                                        and block.get("type") == "text"
                                        and isinstance(block.get("text"), str)
                                    ):
                                        targets.append(
                                            (
                                                block["text"],
                                                lambda updated, obj=block: obj.__setitem__(
                                                    "text", updated
                                                ),
                                            )
                                        )
                if "structuredContent" in result:
                    add_mapping_values(
                        result["structuredContent"],
                        lambda updated, obj=result: obj.__setitem__("structuredContent", updated),
                    )
                if method == "tasks/get":
                    task_result = result.get("result")
                    if isinstance(task_result, dict):
                        content = task_result.get("content")
                        if isinstance(content, list):
                            for block in content:
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "text"
                                    and isinstance(block.get("text"), str)
                                ):
                                    targets.append(
                                        (
                                            block["text"],
                                            lambda updated, obj=block: obj.__setitem__(
                                                "text", updated
                                            ),
                                        )
                                    )
                        if "structuredContent" in task_result:
                            add_mapping_values(
                                task_result["structuredContent"],
                                lambda updated, obj=task_result: obj.__setitem__(
                                    "structuredContent", updated
                                ),
                            )
            return targets

        # Keep the public helper useful for arbitrary text/JSON, while normal
        # MCP requests and responses use the narrower, protocol-aware targets.
        if isinstance(message, dict):
            for key, value in message.items():
                if key not in {"_meta", "jsonrpc", "id", "method"}:
                    add_mapping_values(
                        value, lambda updated, obj=message, k=key: obj.__setitem__(k, updated)
                    )
        elif isinstance(message, list):
            add_mapping_values(message, lambda _updated: None)
        return targets

    def scan_text(
        self,
        text: str,
        agent_id: str = "",
        server_name: str = "",
        direction: str = "response",
        method: str = "",
        context: IdentityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Scan text and return findings without modifying it.

        Returns:
            List of finding dicts with pattern name and match count.
        """
        if not self.enabled:
            return []

        if len(text) > MAX_DLP_INPUT_SIZE:
            raise DLPViolationError(
                pattern_name="DLP_INPUT_TOO_LARGE",
                message="DLP inspection limit exceeded",
            )

        findings: list[dict[str, Any]] = []
        for pat, compiled in self._compiled_patterns:
            if pat.agents and agent_id not in pat.agents:
                continue
            if pat.tenant_ids and (context is None or context.tenant_id not in pat.tenant_ids):
                continue
            if pat.user_ids and (context is None or context.user_id not in pat.user_ids):
                continue
            if pat.servers and server_name not in pat.servers:
                continue
            if pat.methods and method not in pat.methods:
                continue
            if pat.directions and direction not in pat.directions:
                continue
            matches = _findall(compiled, text)
            if matches:
                findings.append(
                    {
                        "pattern": pat.name,
                        "count": len(matches),
                        "mode": pat.mode.value,
                    }
                )

        return findings

    def redact_text(
        self,
        text: str,
        agent_id: str = "",
        server_name: str = "",
        direction: str = "response",
        method: str = "",
        context: IdentityContext | None = None,
    ) -> str:
        """Redact all configured patterns in text.

        Always redacts (ignores BLOCK mode for this method).
        """
        if not self.enabled:
            return text

        if len(text) > MAX_DLP_INPUT_SIZE:
            raise DLPViolationError(
                pattern_name="DLP_INPUT_TOO_LARGE",
                message="DLP inspection limit exceeded",
            )

        result = text
        for pat, compiled in self._compiled_patterns:
            if pat.agents and agent_id not in pat.agents:
                continue
            if pat.tenant_ids and (context is None or context.tenant_id not in pat.tenant_ids):
                continue
            if pat.user_ids and (context is None or context.user_id not in pat.user_ids):
                continue
            if pat.servers and server_name not in pat.servers:
                continue
            if pat.methods and method not in pat.methods:
                continue
            if pat.directions and direction not in pat.directions:
                continue
            result = _sub(compiled, pat.replacement, result)
        return result


def _findall(pattern: Any, text: str) -> list[Any]:
    try:
        if _REGEX_TIMEOUT_SUPPORTED:
            return cast(list[Any], pattern.findall(text, timeout=DLP_REGEX_TIMEOUT_SECONDS))
        return cast(list[Any], pattern.findall(text))
    except TimeoutError as e:
        raise DLPViolationError(
            pattern_name="DLP_REGEX_TIMEOUT",
            message="DLP inspection timed out",
        ) from e


def _sub(pattern: Any, replacement: str, text: str) -> str:
    try:
        if _REGEX_TIMEOUT_SUPPORTED:
            return cast(str, pattern.sub(replacement, text, timeout=DLP_REGEX_TIMEOUT_SECONDS))
        return cast(str, pattern.sub(replacement, text))
    except TimeoutError as e:
        raise DLPViolationError(
            pattern_name="DLP_REGEX_TIMEOUT",
            message="DLP inspection timed out",
        ) from e
