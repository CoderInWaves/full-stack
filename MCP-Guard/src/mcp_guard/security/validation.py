"""Input validation utilities."""

from __future__ import annotations

import re
from typing import Any, Optional

# Pattern to detect potential path traversal
PATH_TRAVERSAL_PATTERN = re.compile(r"\.\./|\.\.\\")


def validate_tool_name(name: Any) -> tuple[bool, Optional[str]]:
    """Validate a tool name is safe."""
    if not isinstance(name, str):
        return False, "Tool name must be a string"
    if not name.strip():
        return False, "Tool name must not be empty"
    if len(name) > 128:
        return False, "Tool name exceeds maximum length"
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        return False, "Tool name must not contain control characters"
    return True, None


def check_path_traversal(path: str) -> bool:
    """Check if a path contains traversal patterns."""
    return bool(PATH_TRAVERSAL_PATTERN.search(path))


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """Sanitize a string for safe use in logs and responses."""
    if len(value) > max_length:
        value = value[:max_length] + "..."
    # Remove control characters
    return re.sub(r"[\x00-\x1f\x7f]", "", value)
