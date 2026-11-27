"""Timing utilities."""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def timer() -> Generator[dict[str, float], None, None]:
    """Context manager that records elapsed time in milliseconds.

    Usage:
        with timer() as t:
            do_work()
        print(t["elapsed_ms"])
    """
    result: dict[str, float] = {"elapsed_ms": 0.0}
    start = time.monotonic()
    try:
        yield result
    finally:
        result["elapsed_ms"] = (time.monotonic() - start) * 1000
