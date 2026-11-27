# Direct REST Action Gateway

MCP-Guard can protect a limited set of direct HTTP API actions. It is not a transparent reverse proxy for arbitrary APIs.

## Configure a pinned action

```yaml
http:
  rest_actions:
    lookup_customer:
      server_name: customer_database
      url: https://customers.internal.example/api/lookup
      method: POST
      upstream_headers:
        Authorization: "Bearer ${CUSTOMER_API_TOKEN}"
```

The action name is a key selected by the gateway caller and also the tool policy name. The administrator fixes its upstream server, full URL, HTTP method, and upstream headers. The caller cannot supply a host, path, method, or forwarding header.

## Request

```http
POST /api/v1/actions/lookup_customer
Authorization: Bearer <AGENT_TOKEN>
Content-Type: application/json

{"customer_id":"C001"}
```

The route authenticates the caller, applies request DLP, checks the same agent/server/tool policy and JSON Schema constraints as `tools/call`, supports `approval_required`, forwards to the configured URL, inspects the response, and audits the decision. The incoming agent `Authorization` header is not copied; only the action's administrator-configured upstream headers are used.

Allowed configured upstream methods: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`. GET actions map scalar JSON properties to query parameters. Nested objects/arrays are rejected for GET. Other methods receive the JSON object as a JSON body.

Approvals return HTTP 202 with an `approval_id`. An administrator decides via `/admin/approvals`; then retry the same body with `Mcp-Guard-Approval-Id`.

## Limits and deployment boundary

The API does not support arbitrary URL forwarding, path-parameter templates, user-supplied headers, streaming/binary responses, or automatic interception of direct network calls. Only mapped actions pass this gateway. Deny direct egress from agents to protected services if the gateway must be mandatory.
