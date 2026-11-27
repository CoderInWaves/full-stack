"""Unit and API tests for approvals and runtime policy snapshots."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from mcp_guard.approval.service import ApprovalService
from mcp_guard.core.exceptions import ConfigurationError
from mcp_guard.core.models import (
    AdminCredential,
    GatewayConfig,
    IdentityContext,
    PolicyAction,
    ToolCallInfo,
)
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.security.tool_controller import AccessController
from mcp_guard.transports.http import HTTPTransport
from tests.conftest import make_tool_call_request


def _approved_call() -> ToolCallInfo:
    context = IdentityContext(
        agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100", roles=["support"]
    )
    return ToolCallInfo(
        request_id=10,
        tool_name="update_customer",
        arguments={"customer_id": "customer-100", "change": {"tier": "gold"}},
        server_name="customer_database",
        agent_id=context.agent_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        roles=context.roles,
        identity_context=context,
    )


def test_approval_binds_action_identity_and_is_one_time() -> None:
    service = ApprovalService(ttl_seconds=60)
    call = _approved_call()
    approval = service.create(call)
    service.decide(approval["approval_id"], "ops-admin", True)

    changed = call.model_copy(deep=True)
    changed.arguments["change"]["tier"] = "platinum"
    ok, reason = service.authorize_once(approval["approval_id"], changed, call.identity_context)
    assert not ok
    assert reason == "APPROVAL_ACTION_MISMATCH"

    ok, reason = service.authorize_once(approval["approval_id"], call, call.identity_context)
    assert ok
    assert reason == "APPROVAL_GRANTED"
    ok, reason = service.authorize_once(approval["approval_id"], call, call.identity_context)
    assert not ok
    assert reason == "APPROVAL_REPLAYED"


def test_approval_required_tool_is_forwarded_only_after_approval(
    sample_config: GatewayConfig,
) -> None:
    controller = AccessController(sample_config)
    router = MessageRouter(sample_config, controller)
    raw = make_tool_call_request(
        "update_customer", {"customer_id": "C001", "change": {"tier": "gold"}}, 21
    )
    forwarded, error = router.process_request(raw, "support-agent-01", "customer_database")
    assert forwarded is None
    assert error is not None
    approval_id = json.loads(error)["error"]["data"]["approval_id"]
    controller.approval_service.decide(approval_id, "ops-admin", True)

    approved_request = json.loads(raw)
    approved_request["params"]["_meta"] = {"io.mcp-guard/approvalId": approval_id}
    forwarded, error = router.process_request(
        json.dumps(approved_request), "support-agent-01", "customer_database"
    )
    assert error is None
    assert forwarded is not None
    assert "io.mcp-guard/approvalId" not in forwarded

    replay, replay_error = router.process_request(
        json.dumps(approved_request), "support-agent-01", "customer_database"
    )
    assert replay is None
    assert replay_error is not None
    assert json.loads(replay_error)["error"]["data"]["reason"] == "APPROVAL_REPLAYED"


def test_runtime_policy_update_is_atomic_and_rollback_is_a_new_version(
    sample_config: GatewayConfig,
) -> None:
    controller = AccessController(sample_config)
    router = MessageRouter(sample_config, controller)
    call = make_tool_call_request("get_customer", {"customer_id": "C001"}, 31)
    assert router.process_request(call, "support-agent-01", "customer_database")[0]

    candidate = sample_config.policy.model_copy(deep=True)
    candidate.agents["support-agent-01"].servers["customer_database"].tools[
        "get_customer"
    ].action = PolicyAction.DENY
    assert controller.policy_manager.update(candidate, "ops-admin") == 2
    assert router.process_request(call, "support-agent-01", "customer_database")[1]

    assert controller.policy_manager.rollback(1, "ops-admin") == 3
    assert router.process_request(call, "support-agent-01", "customer_database")[0]
    assert [entry["version"] for entry in controller.policy_manager.history()] == [1, 2, 3]


def test_runtime_policy_rejects_allow_by_default(sample_config: GatewayConfig) -> None:
    controller = AccessController(sample_config)
    candidate = sample_config.policy.model_copy(deep=True)
    candidate.default_action = PolicyAction.ALLOW
    with pytest.raises(ConfigurationError):
        controller.policy_manager.update(candidate, "ops-admin")


@pytest.mark.asyncio
async def test_admin_api_requires_separate_admin_credential(sample_config: GatewayConfig) -> None:
    sample_config.identity.admin_credentials["ops"] = AdminCredential(
        id="ops-admin", api_key_hash=hashlib.sha256(b"admin-token").hexdigest()
    )
    sample_config.transport = "http"
    transport = HTTPTransport(sample_config)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()), base_url="http://gateway.test"
    )
    try:
        missing = await client.get("/admin/policy")
        wrong_role = await client.get(
            "/admin/policy", headers={"Authorization": "Bearer agent-token"}
        )
        valid = await client.get("/admin/policy", headers={"Authorization": "Bearer admin-token"})
        assert missing.status_code == 401
        assert wrong_role.status_code == 401
        assert valid.status_code == 200
        assert valid.json()["version"] == 1

        updated_policy = valid.json()["policy"]
        updated_policy["agents"]["support-agent-01"]["servers"]["customer_database"]["tools"][
            "get_customer"
        ]["action"] = "deny"
        updated = await client.put(
            "/admin/policy",
            headers={"Authorization": "Bearer admin-token"},
            json={"policy": updated_policy},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2

        queued = transport.tool_controller.approval_service.create(_approved_call())
        unauthenticated_decision = await client.post(
            f"/admin/approvals/{queued['approval_id']}/decision", json={"decision": "approve"}
        )
        approved = await client.post(
            f"/admin/approvals/{queued['approval_id']}/decision",
            headers={"Authorization": "Bearer admin-token"},
            json={"decision": "approve"},
        )
        assert unauthenticated_decision.status_code == 401
        assert approved.status_code == 200
        assert approved.json()["state"] == "approved"
        assert approved.json()["approver_id"] == "ops-admin"
    finally:
        await client.aclose()
        await transport.stop()
