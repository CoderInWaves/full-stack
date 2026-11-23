-- Sliding Window Log using Sorted Set
-- KEYS[1] = sorted set key  e.g. "rl:sw:client123:/api/products"
-- ARGV[1] = limit
-- ARGV[2] = window (seconds)
-- ARGV[3] = unique request id  (prevents score collisions)
-- Returns: {allowed, count, limit}  allowed=1 means permitted

local key    = KEYS[1]
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local req_id = ARGV[3]

-- Use Redis server time to avoid client clock skew
local now_arr = redis.call("TIME")
local now_sec  = tonumber(now_arr[1])
local now_usec = tonumber(now_arr[2])
local now_ms   = now_sec * 1000 + math.floor(now_usec / 1000)

local window_ms  = window * 1000
local cutoff_ms  = now_ms - window_ms

-- Remove timestamps outside the window
redis.call("ZREMRANGEBYSCORE", key, "-inf", cutoff_ms)

-- Count remaining entries
local count = redis.call("ZCARD", key)

local allowed = 0
if count < limit then
    -- Add this request with score = now_ms, member = now_ms:req_id
    redis.call("ZADD", key, now_ms, now_ms .. ":" .. req_id)
    redis.call("PEXPIRE", key, window_ms + 1000)
    allowed = 1
    count = count + 1
end

return {allowed, count, limit, now_ms}
