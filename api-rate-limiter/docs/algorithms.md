# Rate-Limiting Algorithms

## 1. Fixed Window Counter

### What it does
Divides time into fixed buckets (e.g. every 60 seconds). Counts requests per bucket. Rejects when count exceeds limit.

### How it works
- Key: `rl:fw:{client}:{route}:{bucket_number}`
- Bucket number = `floor(current_time / window)`
- Uses Redis INCR (atomic) + EXPIRE

### Example
Limit 10 req/min. At 0:59 client used 9 requests.
- Request at 0:59 → allowed (count=10)
- Request at 1:00 → new bucket, count=1, allowed

### Advantage
Simple, fast, O(1) Redis operations.

### Disadvantage
**Boundary burst**: client can make 10 requests at 0:59 and 10 more at 1:00 — 20 requests in 2 seconds.

### Redis structure
String counter with TTL.

---

## 2. Sliding Window Log

### What it does
Tracks exact timestamp of every request. Only counts requests within the last N seconds from *now*. No boundary burst problem.

### How it works
1. Get current time from Redis server (avoids clock skew)
2. Remove timestamps older than `now - window`
3. Count remaining entries
4. If count < limit → add timestamp, allow
5. If count >= limit → reject

### Example
Limit 10 req/min. At 1:30, window covers 0:30–1:30 exactly.

### Advantage
Precise. No boundary bursts.

### Disadvantage
Stores one entry per request — more memory for high-traffic clients.

### Redis structure
Sorted Set (score = timestamp ms, member = timestamp:uuid). Entire check+add is one Lua script.

---

## 3. Token Bucket

### What it does
Each client has a bucket of tokens. Tokens refill at a constant rate. Each request consumes one token. Allows bursts up to bucket capacity.

### How it works
```
On each request:
  elapsed = now - last_refill
  tokens  = min(capacity, tokens + elapsed * refill_rate)
  if tokens >= 1: consume 1, allow
  else: reject
```

### Example
Capacity 10, refill 1/s. Client sends 10 requests instantly → all allowed. 11th → rejected. After 1s → 1 token refilled → allowed.

### Advantage
Allows controlled bursts. Smooth rate limiting.

### Disadvantage
More complex state. Refill must be atomic.

### Redis structure
Hash with `tokens` and `last_refill` fields. Lua script reads, calculates, updates atomically.

---

## Comparison

| Property        | Fixed Window | Sliding Window | Token Bucket |
|-----------------|-------------|----------------|--------------|
| Boundary bursts | Yes         | No             | Controlled   |
| Memory          | O(1)        | O(requests)    | O(1)         |
| Burst support   | No          | No             | Yes          |
| Accuracy        | Approximate | Exact          | Approximate  |
