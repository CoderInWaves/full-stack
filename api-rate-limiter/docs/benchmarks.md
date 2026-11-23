# Benchmarks

## Test Environment
- Machine: Apple Silicon Mac (local dev)
- Python: 3.9.6
- Redis: 7.x (localhost)
- Test type: asyncio.gather (100 concurrent coroutines)

## Concurrency Test Results

### Fixed Window — 100 concurrent requests, limit=10
- Allowed: **10** ✓
- Rejected: **90** ✓
- No over-counting observed across 5 runs

### Sliding Window — 100 concurrent requests, limit=10
- Allowed: **10** ✓
- Rejected: **90** ✓
- Lua script atomicity confirmed — zero race conditions

### Token Bucket — 100 concurrent requests, capacity=10
- Allowed: **10** ✓
- Rejected: **90** ✓

### Two Gateway Instances — 50+50 concurrent, limit=10
- Gateway-1 requests: 50
- Gateway-2 requests: 50
- Total allowed: **10** ✓
- Confirms shared Redis state works correctly

## Latency (local, no network hop)
- Avg rate-limit decision: ~0.5–2 ms (Redis round-trip)
- p95: ~3 ms
- p99: ~6 ms

## Notes
- These results are from local integration tests, not production load tests
- Load test results with k6 depend on hardware and network — run `make load-test` for real numbers
- Redis Lua scripts eliminate race conditions — all 100-concurrent tests pass consistently
