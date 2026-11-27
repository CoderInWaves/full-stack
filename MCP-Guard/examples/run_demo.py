#!/usr/bin/env python3
"""End-to-end demonstration script for MCP-Guard.

Sends JSON-RPC messages via subprocess stdin/stdout to exercise
the STDIO proxy with the demo server and verifies security behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def send_and_receive(proc, message: dict, timeout: float = 5.0) -> dict | None:
    """Send a JSON-RPC message and read the response."""
    line = json.dumps(message) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()

    # Read response (with timeout via select)
    import select

    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if ready:
        resp_line = proc.stdout.readline()
        if resp_line:
            return json.loads(resp_line.strip())
    return None


def main() -> None:
    print("=" * 60)
    print("MCP-Guard End-to-End Demonstration")
    print("=" * 60)

    demo_temp_dir = tempfile.TemporaryDirectory(prefix="mcp-guard-demo-")
    upstream_call_log = Path(demo_temp_dir.name) / "upstream-calls.jsonl"
    child_env = os.environ.copy()
    child_env["MCP_GUARD_DEMO_CALL_LOG"] = str(upstream_call_log)

    # Start MCP-Guard as STDIO proxy
    cmd = [
        sys.executable,
        "-m",
        "mcp_guard.cli",
        "stdio",
        "--config",
        str(PROJECT_ROOT / "examples" / "demo_config.yaml"),
        "--",
        sys.executable,
        str(PROJECT_ROOT / "examples" / "demo_server.py"),
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=child_env,
    )

    time.sleep(1)  # Let proxy and upstream start

    results = []

    # Test 1: Initialize
    print("\n--- Test 1: Initialize ---")
    resp = send_and_receive(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"capabilities": {}},
        },
    )
    if resp and "result" in resp:
        print(f"  ✅ Initialize succeeded: {resp['result'].get('serverInfo', {}).get('name')}")
        results.append(("Initialize", True))
    else:
        print(f"  ❌ Initialize failed: {resp}")
        results.append(("Initialize", False))

    # Test 2: tools/list (should filter out denied tools)
    print("\n--- Test 2: tools/list (filtering) ---")
    resp = send_and_receive(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        },
    )
    if resp and "result" in resp:
        tool_names = [t["name"] for t in resp["result"].get("tools", [])]
        print(f"  Tools visible to agent: {tool_names}")
        if "delete_customer" not in tool_names:
            print("  ✅ delete_customer correctly filtered from tools/list")
            results.append(("tools/list filtering", True))
        else:
            print("  ❌ delete_customer should be filtered")
            results.append(("tools/list filtering", False))
    else:
        print(f"  ❌ tools/list failed: {resp}")
        results.append(("tools/list filtering", False))

    # Test 3: Allowed tool - get_customer
    print("\n--- Test 3: get_customer (ALLOWED) ---")
    resp = send_and_receive(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_customer", "arguments": {"customer_id": "C001"}},
        },
    )
    if resp and "result" in resp:
        print("  ✅ get_customer ALLOWED — response received")
        # Check DLP redaction on response
        content_text = resp["result"].get("content", [{}])[0].get("text", "")
        if "[REDACTED_EMAIL]" in content_text:
            print("  ✅ DLP redacted email in response")
        elif "@" in content_text:
            print("  ⚠️  Email found in response (DLP may not have matched)")
        results.append(("get_customer ALLOW", True))
    else:
        print(f"  Response: {resp}")
        if resp and "error" in resp:
            print("  ❌ get_customer was denied (should be allowed)")
            results.append(("get_customer ALLOW", False))
        else:
            results.append(("get_customer ALLOW", False))

    # Test 4: Denied tool - delete_customer
    print("\n--- Test 4: delete_customer (DENIED) ---")
    resp = send_and_receive(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "delete_customer",
                "arguments": {"customer_id": "C001", "confirm": True},
            },
        },
    )
    if resp and "error" in resp:
        print(f"  ✅ delete_customer DENIED — error: {resp['error']['message']}")
        print(f"     Request ID preserved: {resp['id'] == 4}")
        results.append(("delete_customer DENY", True))
    else:
        print(f"  ❌ delete_customer should be denied: {resp}")
        results.append(("delete_customer DENY", False))

    # Test 5: Approval-required tool - update_customer
    print("\n--- Test 5: update_customer (APPROVAL_REQUIRED) ---")
    resp = send_and_receive(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "update_customer",
                "arguments": {"customer_id": "C001", "field": "name", "value": "New"},
            },
        },
    )
    if resp and "error" in resp:
        print("  ✅ update_customer BLOCKED (approval required)")
        results.append(("update_customer APPROVAL", True))
    else:
        print(f"  ❌ update_customer should require approval: {resp}")
        results.append(("update_customer APPROVAL", False))

    # Test 6: Unknown tool - should be denied
    print("\n--- Test 6: drop_database (UNKNOWN → DENIED) ---")
    resp = send_and_receive(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "drop_database", "arguments": {}},
        },
    )
    if resp and "error" in resp:
        print("  ✅ drop_database DENIED (unknown tool)")
        results.append(("Unknown tool DENY", True))
    else:
        print(f"  ❌ Unknown tool should be denied: {resp}")
        results.append(("Unknown tool DENY", False))

    # Shutdown
    proc.stdin.close()
    try:
        proc.wait(timeout=10)
        shutdown_ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        shutdown_ok = False
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    if shutdown_ok:
        print("\n  ✅ Proxy and upstream shut down cleanly after client EOF")
    else:
        print("\n  ❌ Proxy required forced shutdown")
    results.append(("Graceful shutdown", shutdown_ok))

    print("\n--- Upstream Enforcement Check ---")
    if upstream_call_log.exists():
        upstream_tools = [
            json.loads(line)["tool"]
            for line in upstream_call_log.read_text(encoding="utf-8").splitlines()
        ]
        blocked_not_forwarded = "get_customer" in upstream_tools and all(
            tool not in upstream_tools
            for tool in ("delete_customer", "update_customer", "drop_database")
        )
        print(f"  Upstream received: {upstream_tools}")
        if blocked_not_forwarded:
            print("  ✅ Denied and approval-required tool calls never reached the upstream")
        else:
            print("  ❌ Unexpected upstream tool calls were recorded")
        results.append(("Blocked calls not forwarded", blocked_not_forwarded))
    else:
        print("  ❌ Upstream call log was not created")
        results.append(("Blocked calls not forwarded", False))

    # Check audit log
    print("\n--- Audit Log Check ---")
    audit_path = PROJECT_ROOT / "logs" / "audit.jsonl"
    if audit_path.exists():
        with open(audit_path) as f:
            lines = f.readlines()
        print(f"  ✅ Audit log exists with {len(lines)} entries")
        for line in lines[-5:]:
            event = json.loads(line)
            print(
                f"     {event.get('tool', 'N/A'):20s} → {event.get('decision', 'N/A'):6s} ({event.get('reason_code', '')})"
            )
        results.append(("Audit logging", True))
    else:
        print("  ❌ Audit log not found")
        results.append(("Audit logging", False))

    # Summary
    print("\n" + "=" * 60)
    print("DEMONSTRATION RESULTS")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n  {passed}/{total} checks passed")
    print("=" * 60)

    demo_temp_dir.cleanup()
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
