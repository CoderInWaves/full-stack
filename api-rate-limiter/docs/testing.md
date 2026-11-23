# Testing Guide

## Prerequisites
- Python venv activated: `source venv/bin/activate`
- Redis running on localhost:6379

## Unit Tests (no Redis needed)

Tests all three algorithms with mocked Redis, policy resolution, and API key auth.

```bash
make test
# or
cd backend && ../venv/bin/pytest tests/unit/ -v
```

Expected: **26 passed**

## Integration Tests (Redis required)

Tests real Lua script execution, key expiry, sorted set behavior, and token refill.

```bash
make integration-test
# or
cd backend && ../venv/bin/pytest tests/integration/ -v
```

Expected: **10 passed**

## Concurrency Tests (Redis required)

Fires 100 simultaneous requests and verifies exactly the configured limit is enforced.
Also tests two limiter instances sharing the same Redis (simulates two gateways).

```bash
cd backend && ../venv/bin/pytest tests/concurrency/ -v
```

Expected: **5 passed**

Key test: `test_shared_state_two_gateway_instances` — 50 requests from limiter-1 + 50 from limiter-2, only 10 allowed total.

## Load Tests (k6 required)

```bash
# Install k6: brew install k6
# Gateway must be running on port 8000
make load-test
```

Set your API key:
```bash
API_KEY=rlk_yourkey k6 run loadtests/rate_limiter.js
```

## Running All Tests

```bash
# Unit only (fast, no Redis)
make test

# Integration + concurrency (needs Redis)
make integration-test
```
