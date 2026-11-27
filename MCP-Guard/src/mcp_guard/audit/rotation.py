"""Log rotation utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mcp_guard.rotation")


def rotate_log_file(
    log_path: str,
    max_size_mb: int = 100,
    backup_count: int = 5,
) -> Optional[str]:
    """Rotate a log file if it exceeds the max size.

    Args:
        log_path: Path to the log file.
        max_size_mb: Maximum size in MB before rotation.
        backup_count: Number of backup files to keep.

    Returns:
        New log file path if rotated, None otherwise.
    """
    path = Path(log_path)
    if not path.exists():
        return None

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb < max_size_mb:
        return None

    # Rotate existing backups
    for i in range(backup_count - 1, 0, -1):
        src = Path(f"{path}.{i}")
        dst = Path(f"{path}.{i + 1}")
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)

    # Move current to .1
    backup = Path(f"{path}.1")
    if backup.exists():
        backup.unlink()
    path.rename(backup)

    logger.info("Rotated log file %s -> %s", log_path, backup)
    return str(path)
