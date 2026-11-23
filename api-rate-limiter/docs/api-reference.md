# API Reference

Base URL: `http://localhost:8000`

## Authentication

### Admin routes
All `/admin/api/v1/*` routes require:
```
Authorization: Bearer dev-admin-token-change-in-production
```

### Gateway routes
All `/api/*` routes require:
```
X-API-Key: rlk_your_key_here
```

---

## Auth

### POST /admin/api/v1/auth/login
```json
{ "token": "dev-admin-token-change-in-production" }
```
Response:
```json
{ "access_token": "dev-admin-token-change-in-production", "token_type": "bearer" }
```

---

## Overview

### GET /admin/api/v1/overview?window=3600
Returns aggregate stats for the given time window (seconds).
```json
{
  "total_requests": 150,
  "allowed_requests": 120,
  "rejected_requests": 30,
  "total_clients": 2,
  "active_policies": 3,
  "requests_per_second": 0.042,
  "avg_latency_ms": 12.4,
  "p95_latency_ms": 28.1,
  "p99_latency_ms": 45.2
}
```

---

## Analytics

### GET /admin/api/v1/analytics?window=3600
```json
{
  "time_series": [{ "timestamp": 1700000000, "total": 10, "allowed": 8, "rejected": 2 }],
  "by_route":    [{ "route": "/api/products", "total": 80, "allowed": 70, "rejected": 10 }],
  "by_client":   [{ "client_id": "client_abc", "client_name": "Dev Basic", "total": 50, "rejected": 5 }],
  "by_algorithm":{ "sliding_window": 100, "fixed_window": 50 }
}
```

---

## Health

### GET /admin/api/v1/health
```json
{
  "overall": "healthy",
  "gateway_id": "gateway-1",
  "uptime_seconds": 3600.0,
  "services": [
    { "name": "redis",        "status": "healthy", "latency_ms": 0.4 },
    { "name": "demo_backend", "status": "healthy", "latency_ms": 5.2 },
    { "name": "gateway (gateway-1)", "status": "healthy" }
  ]
}
```

---

## Clients

### GET /admin/api/v1/clients
Returns array of all clients.

### POST /admin/api/v1/clients
```json
{ "name": "My App", "tier": "basic" }
```
Response includes `api_key` — shown only once.

### PATCH /admin/api/v1/clients/{id}
```json
{ "enabled": false }
```

### DELETE /admin/api/v1/clients/{id}
```json
{ "deleted": true }
```

---

## Policies

### GET /admin/api/v1/policies
Returns array of all policies.

### POST /admin/api/v1/policies
```json
{
  "client_id": "client_abc123",
  "method": "GET",
  "route": "/api/products",
  "algorithm": "sliding_window",
  "limit": 10,
  "window": 60,
  "bucket_capacity": null,
  "refill_rate": null,
  "enabled": true
}
```

### PUT /admin/api/v1/policies/{id}
```json
{ "limit": 20, "algorithm": "token_bucket", "bucket_capacity": 20, "refill_rate": 2.0 }
```

### DELETE /admin/api/v1/policies/{id}
```json
{ "deleted": true }
```

---

## Gateway (Public)

### GET /api/products
### GET /api/users
### POST /api/orders
### GET /api/health

All require `X-API-Key` header.

**Success response headers:**
```
X-RateLimit-Limit:     10
X-RateLimit-Remaining: 7
X-RateLimit-Reset:     1700000060
X-RateLimit-Algorithm: sliding_window
X-Gateway-ID:          gateway-1
```

**HTTP 429 response:**
```json
{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again later.",
  "retry_after": 45
}
```
