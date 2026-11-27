"""MCP-Guard CLI — Command-line interface."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from typing import Optional

import click

from mcp_guard import __version__
from mcp_guard.core.config import load_config, validate_config
from mcp_guard.core.exceptions import ConfigurationError
from mcp_guard.core.models import GatewayConfig


def _setup_logging(level: str = "INFO") -> None:
    """Configure logging to stderr only (never to stdout)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger("mcp_guard")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False


def _report_config_issues(cfg: GatewayConfig) -> bool:
    """Print validation findings and return whether the configuration is valid."""
    is_valid, issues = validate_config(cfg)
    for issue in issues:
        if issue.startswith("WARNING:"):
            click.echo(f"⚠️  {issue}", err=True)
        else:
            click.echo(f"❌ {issue}", err=True)
    return is_valid


@click.group()
@click.version_option(version=__version__, prog_name="mcp-guard")
def cli() -> None:
    """MCP-Guard: The Agentic Firewall.

    A security proxy for MCP tool invocations that enforces
    identity, policy, and data protection.
    """


@cli.command("hash-token")
def hash_token_cmd() -> None:
    """Read a token without echoing it and print its SHA-256 config value."""
    token = click.prompt("HTTP API token", hide_input=True, confirmation_prompt=True)
    if not token:
        raise click.ClickException("Token must not be empty")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    click.echo(f"sha256:{digest}")


@cli.command("validate-config")
@click.option("--config", "-c", required=True, help="Path to configuration YAML file.")
@click.option("--policy", "-p", default=None, help="Path to separate policy YAML file.")
@click.option("--agents", "-a", default=None, help="Path to separate agents YAML file.")
def validate_config_cmd(config: str, policy: Optional[str], agents: Optional[str]) -> None:
    """Validate configuration files without starting the gateway."""
    _setup_logging("INFO")

    try:
        cfg = load_config(config, policy_path=policy, agents_path=agents)
        is_valid = _report_config_issues(cfg)

        if is_valid:
            click.echo("✅ Configuration is valid.", err=True)
            sys.exit(0)
        else:
            click.echo("❌ Configuration has errors.", err=True)
            sys.exit(1)

    except ConfigurationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
        sys.exit(1)


@cli.command("doctor")
@click.option("--config", "-c", required=True, help="Path to configuration YAML file.")
def doctor_cmd(config: str) -> None:
    """Run diagnostics on the configuration and environment."""
    _setup_logging("INFO")

    click.echo("🔍 MCP-Guard Doctor", err=True)
    click.echo(f"   Version: {__version__}", err=True)
    click.echo(f"   Python: {sys.version}", err=True)
    python_supported = sys.version_info >= (3, 11)
    click.echo(
        f"{'✅' if python_supported else '❌'} Python 3.11+ requirement "
        f"({'satisfied' if python_supported else 'not satisfied'})",
        err=True,
    )
    click.echo("", err=True)

    # Check config
    try:
        cfg = load_config(config)
        click.echo(f"✅ Configuration loaded from {config}", err=True)
        is_valid = _report_config_issues(cfg)
    except ConfigurationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
        sys.exit(1)

    # Check dependencies
    deps = ["pydantic", "yaml", "httpx", "starlette", "uvicorn", "jsonschema", "click", "regex"]
    dependency_errors = not python_supported
    for dep in deps:
        try:
            __import__(dep)
            click.echo(f"✅ {dep} is available", err=True)
        except ImportError:
            click.echo(f"❌ {dep} is NOT available", err=True)
            dependency_errors = True

    # Check transport config
    click.echo(f"\n   Transport: {cfg.transport}", err=True)
    click.echo(f"   Default policy: {cfg.default_policy.value}", err=True)
    click.echo(f"   DLP enabled: {cfg.security.enable_dlp}", err=True)
    click.echo(f"   Agents configured: {len(cfg.identity.agents)}", err=True)
    click.echo(f"   Policy agents: {len(cfg.policy.agents)}", err=True)

    if cfg.transport == "stdio" and cfg.stdio:
        click.echo(f"   Upstream: {cfg.stdio.upstream.name}", err=True)
        if cfg.stdio.upstream.command:
            click.echo(f"   Command: {' '.join(cfg.stdio.upstream.command)}", err=True)

    if not is_valid or dependency_errors:
        click.echo("\n❌ Doctor found blocking issues.", err=True)
        sys.exit(1)
    click.echo("\n✅ Doctor check complete.", err=True)


@cli.command("stdio")
@click.option("--config", "-c", required=True, help="Path to configuration YAML file.")
@click.option("--policy", "-p", default=None, help="Path to separate policy YAML file.")
@click.option("--agents", "-a", default=None, help="Path to separate agents YAML file.")
@click.argument("upstream_command", nargs=-1, required=False)
def stdio_cmd(
    config: str,
    policy: Optional[str],
    agents: Optional[str],
    upstream_command: tuple[str, ...],
) -> None:
    """Start MCP-Guard as a STDIO proxy.

    Optionally pass the upstream command after '--':
        mcp-guard stdio --config config.yaml -- python server.py
    """
    _setup_logging()

    try:
        cfg = load_config(config, policy_path=policy, agents_path=agents)
    except ConfigurationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
        sys.exit(1)

    # Determine upstream command
    cmd_list: list[str] = list(upstream_command)
    if not cmd_list and cfg.stdio and cfg.stdio.upstream.command:
        cmd_list = cfg.stdio.upstream.command

    if not cmd_list:
        click.echo(
            "❌ No upstream command specified. Use -- command or configure in YAML.", err=True
        )
        sys.exit(1)

    cfg.transport = "stdio"
    if not _report_config_issues(cfg):
        sys.exit(1)
    _setup_logging(cfg.logging.level)

    from mcp_guard.transports.stdio import STDIOTransport

    env = {}
    if cfg.stdio and cfg.stdio.upstream.env:
        env = cfg.stdio.upstream.env

    transport = STDIOTransport(cfg, cmd_list, upstream_env=env)

    try:
        asyncio.run(transport.start())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.getLogger("mcp_guard").error("STDIO proxy failed: %s", e)
        sys.exit(1)


@cli.command("http")
@click.option("--config", "-c", required=True, help="Path to configuration YAML file.")
@click.option("--policy", "-p", default=None, help="Path to separate policy YAML file.")
@click.option("--agents", "-a", default=None, help="Path to separate agents YAML file.")
@click.option("--host", default=None, help="Override bind host.")
@click.option("--port", default=None, type=int, help="Override bind port.")
def http_cmd(
    config: str,
    policy: Optional[str],
    agents: Optional[str],
    host: Optional[str],
    port: Optional[int],
) -> None:
    """Start MCP-Guard as an HTTP gateway."""
    _setup_logging()

    try:
        cfg = load_config(config, policy_path=policy, agents_path=agents)
    except ConfigurationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
        sys.exit(1)

    from mcp_guard.core.models import HTTPTransportConfig

    cfg.transport = "http"
    if cfg.http is None:
        cfg.http = HTTPTransportConfig()
    if host:
        cfg.http.host = host
    if port:
        cfg.http.port = port
    if not _report_config_issues(cfg):
        sys.exit(1)
    _setup_logging(cfg.logging.level)

    from mcp_guard.transports.http import HTTPTransport

    transport = HTTPTransport(cfg)

    try:
        asyncio.run(transport.start())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.getLogger("mcp_guard").error("HTTP gateway failed: %s", e)
        sys.exit(1)


def main() -> None:
    """Entry point for mcp-guard CLI."""
    cli()


if __name__ == "__main__":
    main()
