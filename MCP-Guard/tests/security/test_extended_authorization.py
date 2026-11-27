"""Security coverage for resource, prompt, task, and extension requests."""

from __future__ import annotations

import json

from mcp_guard.core.models import (
    ArgumentConstraint,
    GatewayConfig,
    IdentityContext,
    PolicyAction,
    ToolPolicy,
)
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.security.tool_controller import AccessController
from tests.conftest import make_jsonrpc_request, make_tool_call_request


def _router(config: GatewayConfig) -> tuple[MessageRouter, AccessController]:
    controller = AccessController(config)
    return MessageRouter(config, controller), controller


def test_resource_read_is_scoped_to_tenant_and_user(sample_config: GatewayConfig) -> None:
    rules = sample_config.policy.agents["support-agent-01"].servers["customer_database"].resources
    rules["company://{tenant_id}/customers/{user_id}"] = ToolPolicy(action=PolicyAction.ALLOW)
    router, _ = _router(sample_config)
    context = IdentityContext(
        agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100"
    )

    own = make_jsonrpc_request("resources/read", {"uri": "company://bank-a/customers/customer-100"})
    other = make_jsonrpc_request(
        "resources/read", {"uri": "company://bank-a/customers/customer-200"}, 2
    )
    cross_tenant = make_jsonrpc_request(
        "resources/read", {"uri": "company://bank-b/customers/customer-100"}, 3
    )

    assert (
        router.process_request(own, context.agent_id, "customer_database", context)[0] is not None
    )
    assert router.process_request(other, context.agent_id, "customer_database", context)[1]
    assert router.process_request(cross_tenant, context.agent_id, "customer_database", context)[1]


def test_tool_arguments_cannot_impersonate_another_tenant_or_user(
    sample_config: GatewayConfig,
) -> None:
    rule = (
        sample_config.policy.agents["support-agent-01"]
        .servers["customer_database"]
        .tools["get_customer"]
    )
    rule.identity_argument_bindings = {"tenant_id": "tenant_id", "user_id": "user_id"}
    router, _ = _router(sample_config)
    context = IdentityContext(
        agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100"
    )

    own = make_tool_call_request(
        "get_customer",
        {"tenant_id": "bank-a", "user_id": "customer-100", "customer_id": "C001"},
    )
    forged_tenant = make_tool_call_request(
        "get_customer",
        {"tenant_id": "bank-b", "user_id": "customer-100", "customer_id": "C002"},
        2,
    )
    forged_user = make_tool_call_request(
        "get_customer",
        {"tenant_id": "bank-a", "user_id": "customer-200", "customer_id": "C002"},
        3,
    )

    assert router.process_request(own, context.agent_id, "customer_database", context)[0]
    assert router.process_request(forged_tenant, context.agent_id, "customer_database", context)[1]
    assert router.process_request(forged_user, context.agent_id, "customer_database", context)[1]


def test_resource_discovery_filters_to_explicit_grants(sample_config: GatewayConfig) -> None:
    rules = sample_config.policy.agents["support-agent-01"].servers["customer_database"].resources
    rules["company://customers/customer-100"] = ToolPolicy(action=PolicyAction.ALLOW)
    rules["company://customers/customer-200"] = ToolPolicy(action=PolicyAction.DENY)
    router, _ = _router(sample_config)
    response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "result": {
                "resources": [
                    {"uri": "company://customers/customer-100"},
                    {"uri": "company://customers/customer-200"},
                    {"uri": "company://customers/customer-300"},
                ],
                "nextCursor": "opaque-upstream-cursor",
            },
        }
    )

    processed = router.process_response(
        response, "support-agent-01", "customer_database", "resources/list"
    )
    result = json.loads(processed)["result"]
    assert result["resources"] == [{"uri": "company://customers/customer-100"}]
    assert "nextCursor" not in result


def test_prompt_get_checks_name_and_argument_schema(sample_config: GatewayConfig) -> None:
    server = sample_config.policy.agents["support-agent-01"].servers["customer_database"]
    server.prompts["customer_summary"] = ToolPolicy(
        action=PolicyAction.ALLOW,
        argument_constraints=ArgumentConstraint(
            json_schema={
                "type": "object",
                "properties": {"style": {"type": "string", "enum": ["short", "full"]}},
                "required": ["style"],
                "additionalProperties": False,
            }
        ),
    )
    router, _ = _router(sample_config)
    allowed = make_jsonrpc_request(
        "prompts/get", {"name": "customer_summary", "arguments": {"style": "short"}}
    )
    invalid_arguments = make_jsonrpc_request(
        "prompts/get", {"name": "customer_summary", "arguments": {"style": "admin"}}, 2
    )
    unlisted = make_jsonrpc_request("prompts/get", {"name": "system_prompt", "arguments": {}}, 3)

    assert router.process_request(allowed, "support-agent-01", "customer_database")[0]
    assert router.process_request(invalid_arguments, "support-agent-01", "customer_database")[1]
    assert router.process_request(unlisted, "support-agent-01", "customer_database")[1]


def test_unknown_method_requires_explicit_allow_rule(sample_config: GatewayConfig) -> None:
    router, _ = _router(sample_config)
    request = make_jsonrpc_request("vendor/execute", {"command": "run"}, 7)
    assert router.process_request(request, "support-agent-01", "customer_database")[1]

    server = sample_config.policy.agents["support-agent-01"].servers["customer_database"]
    server.methods["vendor/execute"] = PolicyAction.ALLOW
    router, _ = _router(sample_config)
    assert router.process_request(request, "support-agent-01", "customer_database")[0]


def test_task_operations_are_bound_to_creator_and_explicit_method_policy(
    sample_config: GatewayConfig,
) -> None:
    server = sample_config.policy.agents["support-agent-01"].servers["customer_database"]
    server.methods["tasks/get"] = PolicyAction.ALLOW
    router, _ = _router(sample_config)
    owner_context = IdentityContext(
        agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100"
    )
    tool_request = make_tool_call_request("get_customer", {"customer_id": "customer-100"}, 21)
    assert router.process_request(
        tool_request, owner_context.agent_id, "customer_database", owner_context
    )[0]

    task_response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "result": {"resultType": "task", "taskId": "task-1", "ttlMs": 30000},
        }
    )
    router.process_response_with_decision(
        task_response,
        owner_context.agent_id,
        "customer_database",
        "tools/call",
        owner_context,
        21,
    )

    task_get = make_jsonrpc_request("tasks/get", {"taskId": "task-1"}, 22)
    assert router.process_request(
        task_get, owner_context.agent_id, "customer_database", owner_context
    )[0]
    other_context = IdentityContext(
        agent_id="support-agent-01", tenant_id="bank-b", user_id="customer-200"
    )
    assert router.process_request(
        task_get, owner_context.agent_id, "customer_database", other_context
    )[1]


def test_subscriptions_filter_resource_uris(sample_config: GatewayConfig) -> None:
    server = sample_config.policy.agents["support-agent-01"].servers["customer_database"]
    server.methods["subscriptions/listen"] = PolicyAction.ALLOW
    server.resources["company://customers/customer-100"] = ToolPolicy(action=PolicyAction.ALLOW)
    router, _ = _router(sample_config)
    request = make_jsonrpc_request(
        "subscriptions/listen",
        {
            "notifications": {
                "resourcesListChanged": True,
                "resourceSubscriptions": [
                    "company://customers/customer-100",
                    "company://customers/customer-200",
                ],
            }
        },
    )
    forwarded, error = router.process_request(request, "support-agent-01", "customer_database")

    assert error is None
    assert forwarded is not None
    assert json.loads(forwarded)["params"]["notifications"] == {
        "resourcesListChanged": True,
        "resourceSubscriptions": ["company://customers/customer-100"],
    }


def test_subscription_response_drops_unowned_resource_events(
    sample_config: GatewayConfig,
) -> None:
    server = sample_config.policy.agents["support-agent-01"].servers["customer_database"]
    server.methods["subscriptions/listen"] = PolicyAction.ALLOW
    server.resources["company://customers/customer-100"] = ToolPolicy(action=PolicyAction.ALLOW)
    router, _ = _router(sample_config)
    event = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "notifications/resources/updated",
            "params": {"uri": "company://customers/customer-200"},
        }
    )

    processed, reason = router.process_response_with_decision(
        event, "support-agent-01", "customer_database", "subscriptions/listen"
    )
    assert processed == ""
    assert reason == "SUBSCRIPTION_EVENT_FILTERED"


def test_approval_required_does_not_skip_argument_validation(sample_config: GatewayConfig) -> None:
    rule = (
        sample_config.policy.agents["support-agent-01"]
        .servers["customer_database"]
        .tools["update_customer"]
    )
    rule.argument_constraints = ArgumentConstraint(
        json_schema={"type": "object", "required": ["change"]}
    )
    router, _ = _router(sample_config)
    request = make_tool_call_request("update_customer", {}, 30)
    error = router.process_request(request, "support-agent-01", "customer_database")[1]

    assert error is not None
    assert json.loads(error)["error"]["data"]["reason"] == "INVALID_ARGUMENTS"


def test_lifecycle_and_cancellation_notifications_remain_forwardable(
    sample_config: GatewayConfig,
) -> None:
    router, _ = _router(sample_config)
    for method in ("notifications/initialized", "notifications/cancelled"):
        message = json.dumps({"jsonrpc": "2.0", "method": method, "params": {}})
        assert router.process_request(message, "support-agent-01", "customer_database")[0]

    unknown = json.dumps({"jsonrpc": "2.0", "method": "vendor/unknown", "params": {}})
    assert router.process_request(unknown, "support-agent-01", "customer_database") == (None, None)
