"""Demo MCP Server for MCP-Guard testing.

A simple MCP server that exposes fake customer management tools
over STDIO (newline-delimited JSON-RPC).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

# Fake customer database
CUSTOMERS: dict[str, dict[str, Any]] = {
    "C001": {
        "id": "C001",
        "name": "Alice Johnson",
        "email": "alice.johnson@example.com",
        "phone": "+1-555-0101",
        "status": "active",
        "tier": "premium",
    },
    "C002": {
        "id": "C002",
        "name": "Bob Smith",
        "email": "bob.smith@example.com",
        "phone": "+1-555-0102",
        "status": "active",
        "tier": "standard",
    },
    "C003": {
        "id": "C003",
        "name": "Charlie Brown",
        "email": "charlie@example.com",
        "phone": "+1-555-0103",
        "status": "inactive",
        "tier": "basic",
    },
}

# Track which tools were called (for testing verification)
CALL_LOG: list[dict[str, Any]] = []

# Tool definitions
TOOLS = [
    {
        "name": "get_customer",
        "description": "Retrieve customer information by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "search_customer",
        "description": "Search customers by name",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_report",
        "description": "Generate a customer report",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["summary", "detailed"],
                    "description": "Report type",
                },
            },
            "required": ["report_type"],
        },
    },
    {
        "name": "update_customer",
        "description": "Update customer information",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "field": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["customer_id", "field", "value"],
        },
    },
    {
        "name": "delete_customer",
        "description": "Delete a customer record (DESTRUCTIVE)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["customer_id", "confirm"],
        },
    },
]


def handle_request(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Handle a JSON-RPC request."""
    method = data.get("method")
    params = data.get("params", {})
    req_id = data.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "demo-customer-server", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        # Notification — no response needed
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        CALL_LOG.append({"tool": tool_name, "arguments": arguments})
        call_log_path = os.environ.get("MCP_GUARD_DEMO_CALL_LOG")
        if call_log_path:
            with open(call_log_path, "a", encoding="utf-8") as call_log:
                call_log.write(json.dumps({"tool": tool_name}) + "\n")

        result = execute_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool and return the result."""
    if tool_name == "get_customer":
        cid = arguments.get("customer_id", "")
        customer = CUSTOMERS.get(cid)
        if customer:
            return {
                "content": [{"type": "text", "text": json.dumps(customer)}],
                "isError": False,
            }
        return {
            "content": [{"type": "text", "text": f"Customer {cid} not found"}],
            "isError": True,
        }

    if tool_name == "search_customer":
        query = arguments.get("query", "").lower()
        results = [c for c in CUSTOMERS.values() if query in c["name"].lower()]
        return {
            "content": [{"type": "text", "text": json.dumps(results)}],
            "isError": False,
        }

    if tool_name == "generate_report":
        report_type = arguments.get("report_type", "summary")
        if report_type == "summary":
            report = {
                "total_customers": len(CUSTOMERS),
                "active": sum(1 for c in CUSTOMERS.values() if c["status"] == "active"),
                "inactive": sum(1 for c in CUSTOMERS.values() if c["status"] == "inactive"),
            }
        else:
            report = {"customers": list(CUSTOMERS.values())}
        return {
            "content": [{"type": "text", "text": json.dumps(report)}],
            "isError": False,
        }

    if tool_name == "update_customer":
        cid = arguments.get("customer_id", "")
        field = arguments.get("field", "")
        value = arguments.get("value", "")
        customer = CUSTOMERS.get(cid)
        if customer and field in customer:
            customer[field] = value
            return {
                "content": [{"type": "text", "text": f"Updated {field} for {cid}"}],
                "isError": False,
            }
        return {
            "content": [{"type": "text", "text": "Cannot update: customer or field not found"}],
            "isError": True,
        }

    if tool_name == "delete_customer":
        cid = arguments.get("customer_id", "")
        confirm = arguments.get("confirm", False)
        if cid in CUSTOMERS and confirm:
            del CUSTOMERS[cid]
            return {
                "content": [{"type": "text", "text": f"Deleted customer {cid}"}],
                "isError": False,
            }
        return {
            "content": [{"type": "text", "text": "Delete not confirmed or customer not found"}],
            "isError": True,
        }

    return {
        "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
        "isError": True,
    }


def main() -> None:
    """Main loop — read JSON-RPC from stdin, respond on stdout."""
    # All logging goes to stderr

    sys.stderr.write("Demo MCP server started\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            error_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(data)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
