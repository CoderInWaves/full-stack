# Architecture

## Overview

```
API Clients
     │
     ▼
  Nginx (port 8080)
  Load Balancer
     │
  ┌──┴──┐
  │     │
  ▼     ▼
GW-1  GW-2   (FastAPI, port 8000)
  │     │
  └──┬──┘
     │
     ▼
   Redis        ← shared rate-limit state
     │
     ▼
Rate-Limit Decision
  ┌──┴──┐
  │     │
Allow  Reject
  │     │
  ▼     ▼
Demo  HTTP 429
Backend
```

## Components

### Nginx
- Listens on port 8080
- Round-robin load balances across gateway-1 and gateway-2
- Proxies frontend, admin API, and gateway API

### FastAPI Gateway
- Receives every API request
- Runs: auth → policy resolution → rate-limit algorithm → proxy or reject
- Two instances share the same Redis — neither uses local memory for counters

### Redis
- Single source of truth for all rate-limit counters
- Lua scripts ensure atomic read-modify-write
- Persistence enabled (AOF) so policies/clients survive restarts

### Rate-Limit Middleware
Applied to all `/api/*` routes. Bypasses `/admin`, `/health`, `/docs`.

### Reverse Proxy
Uses HTTPX to forward allowed requests to the demo backend. Handles timeouts and connection errors gracefully.

## Request Lifecycle

1. Client sends `GET /api/products` with `X-API-Key: rlk_xxx`
2. Nginx forwards to one of the two gateways
3. Middleware extracts API key, hashes it, looks up client in Redis
4. Policy resolver finds the best matching policy (client+method+route → client → global)
5. Rate-limit algorithm runs Lua script atomically in Redis
6. If allowed: request forwarded to demo backend, response returned with rate-limit headers
7. If rejected: HTTP 429 returned immediately with `retry_after`

## Distributed State

Both gateways share one Redis instance. A client sending 4 requests to GW-1 and 6 to GW-2 will be rejected on the 11th request regardless of which gateway receives it — because the counter lives in Redis, not in application memory.

## Fail Behavior

- `FAIL_OPEN=false` (default): if Redis is unreachable, return 503
- `FAIL_OPEN=true`: if Redis is unreachable, allow the request through
