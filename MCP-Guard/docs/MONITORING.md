# Monitoring and Observability

## Health endpoints

- `GET /health` and `GET /health/live`: process liveness and version.
- `GET /health/ready`: configuration readiness, upstream configured/recently reachable state, and policy/DLP engine status. Upstream state is `unknown` until a request has reached it.

Health routes are unauthenticated and disclose only basic service status. They do not make authorization decisions.

## Prometheus metrics

`GET /metrics` requires an administrator bearer token. Metrics use bounded method/decision labels and do not label agents, tenants, tools, URIs, or payload values. Exposed counters include request decisions, auth failures, upstream failures, and DLP blocks. A request latency histogram is emitted per bounded MCP method.

## OpenTelemetry

Install optional OTLP support into the project virtual environment and set the standard exporter endpoint:

```bash
.venv/bin/python -m pip install -e '.[telemetry]'
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
```

The gateway emits spans around HTTP authentication, request authorization/inspection, upstream forwarding, and response inspection. It does not attach payloads, tokens, argument values, or customer identifiers. If the package or collector is unavailable, trace export is disabled or reports a setup warning; authorization remains active.

This project environment did not include the optional telemetry extra or a collector, so exporter interoperability has not been integration-tested here. Prometheus counters are built-in and independent from tracing.

## Audit events

JSONL audit records include time, identity context, operation, decision, reason, correlation ID, and latency. Arguments and responses are omitted unless explicitly enabled. Protect and rotate audit files according to the data classification of your environment.
