# Distributed API Rate Limiter

A production-grade distributed API rate limiter built with Python (FastAPI) and React. Designed as an SDE internship portfolio project demonstrating distributed systems, Redis, async programming, and full-stack development.

## What It Does

Controls how many API requests a client can make in a given time window. When a client exceeds their limit, the gateway returns HTTP 429 (Too Many Requests) and tells them when to retry.

## Quick Start (Local without Docker)

### Prerequisites
- Python 3.9+
- Node.js 18+
- Redis running on localhost:6379

### 1. Start Redis
```bash
brew install redis && brew services start redis
# or: redis-server
```

### 2. Start Demo Backend
```bash
cd backend
source ../venv/bin/activate
uvicorn demo_backend:app --port 8001 --reload
```

### 3. Start Gateway
```bash
cd backend
source ../venv/bin/activate
uvicorn app.main:app --port 8000 --reload
```

### 4. Start Frontend
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

## Quick Start (Docker)
```bash
make build
make up
# Open http://localhost:8080
```

## Admin Login
- URL: http://localhost:5173 (or http://localhost:8080 with Docker)
- Default token: `dev-admin-token-change-in-production`

## Creating an API Client
1. Go to **Clients** page → **New Client**
2. Enter name and tier (basic/premium)
3. Copy the API key shown — it is displayed only once

## Testing an API Request
```bash
curl -H "X-API-Key: YOUR_KEY" http://localhost:8000/api/products
```

Or use the **API Console** page in the dashboard.

## Rate Limit Response Headers
Every response includes:
```
X-RateLimit-Limit:     10
X-RateLimit-Remaining: 7
X-RateLimit-Reset:     1700000060
X-RateLimit-Algorithm: sliding_window
X-Gateway-ID:          gateway-1
```

When rate limited (HTTP 429):
```json
{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again later.",
  "retry_after": 45
}
```

## Running Tests
```bash
# Unit tests (no Redis needed)
make test

# Integration + concurrency tests (Redis required)
make integration-test

# Load tests (k6 required, gateway must be running)
make load-test
```

## Technology Stack
| Layer      | Technology                        |
|------------|-----------------------------------|
| Gateway    | Python 3.9, FastAPI, Uvicorn      |
| Rate Limit | Redis 7, Lua scripts (atomic)     |
| Proxy      | HTTPX async reverse proxy         |
| Frontend   | React 18, TypeScript, Vite        |
| Charts     | Recharts                          |
| Styling    | Tailwind CSS                      |
| Load Balancer | Nginx                          |
| Containers | Docker, Docker Compose            |
| Testing    | Pytest, pytest-asyncio, k6        |

## Project Structure
```
backend/
  app/
    limiter/        # Fixed window, sliding window, token bucket
    middleware/     # Rate-limit middleware
    auth/           # API key + admin auth
    policies/       # Policy CRUD + resolution
    clients/        # Client management
    analytics/      # Metrics collection
    proxy/          # Reverse proxy to demo backend
    api/            # Public + admin routes
  tests/
    unit/           # Algorithm unit tests (mocked Redis)
    integration/    # Real Redis tests
    concurrency/    # 100-concurrent-request tests
  demo_backend.py   # Simulated API backend
frontend/
  src/
    pages/          # Dashboard, Analytics, Policies, Clients, Console, Health
    components/     # StatCard, Toast, Spinner, ConfirmDialog
    services/       # Axios API client
    contexts/       # Auth context
nginx/nginx.conf    # Load balancer config
loadtests/          # k6 load test scripts
docs/               # Architecture, algorithms, API reference
```

## Security Notes
- API keys are SHA-256 hashed before storage — raw keys are never stored
- Admin token is environment-variable configured
- Never commit real tokens to version control
- Default dev credentials are not suitable for production
