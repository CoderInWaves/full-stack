"""Pre-load Lua scripts into Redis and cache their SHAs."""
import os
import logging

logger = logging.getLogger(__name__)

_SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "limiter", "lua_scripts")

_SCRIPTS = {
    "fixed_window": "fixed_window.lua",
    "sliding_window": "sliding_window.lua",
    "token_bucket": "token_bucket.lua",
}

_shas: dict[str, str] = {}


def _load_script(name: str) -> str:
    path = os.path.join(_SCRIPT_DIR, _SCRIPTS[name])
    with open(path, "r") as f:
        return f.read()


async def load_scripts(redis) -> None:
    for name in _SCRIPTS:
        src = _load_script(name)
        sha = await redis.script_load(src)
        _shas[name] = sha
        logger.info(f"Loaded Lua script '{name}' → SHA {sha[:8]}…")


def get_sha(name: str) -> str:  # type: ignore
    if name not in _shas:
        raise RuntimeError(f"Script '{name}' not loaded. Call load_scripts() first.")
    return _shas[name]


def get_source(name: str) -> str:  # type: ignore
    return _load_script(name)
