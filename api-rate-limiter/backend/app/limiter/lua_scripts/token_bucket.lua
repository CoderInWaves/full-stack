-- Token Bucket
-- KEYS[1] = bucket key  e.g. "rl:tb:client123:/api/products"
-- ARGV[1] = capacity   (max tokens)
-- ARGV[2] = refill_rate (tokens per second, float)
-- ARGV[3] = ttl (seconds, for key expiry)
-- Returns: {allowed, tokens_left, capacity}  allowed=1 means permitted

local key         = KEYS[1]
local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local ttl         = tonumber(ARGV[3])

-- Use Redis server time
local now_arr  = redis.call("TIME")
local now_sec  = tonumber(now_arr[1])
local now_usec = tonumber(now_arr[2])
local now      = now_sec + now_usec / 1000000

-- Read existing bucket state
local data = redis.call("HMGET", key, "tokens", "last_refill")
local tokens      = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    -- New bucket: start full
    tokens      = capacity
    last_refill = now
end

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
local refill  = elapsed * refill_rate
tokens = math.min(capacity, tokens + refill)
last_refill = now

local allowed = 0
if tokens >= 1 then
    tokens  = tokens - 1
    allowed = 1
end

-- Persist updated state
redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
redis.call("EXPIRE", key, ttl)

local tokens_int = math.floor(tokens)
return {allowed, tokens_int, capacity}
