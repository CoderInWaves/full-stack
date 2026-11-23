-- Fixed Window Counter
-- KEYS[1] = rate limit key  e.g. "rl:fw:client123:/api/products:1700000000"
-- ARGV[1] = limit (max requests)
-- ARGV[2] = window (seconds, for expiry)
-- Returns: {count, limit, allowed}  allowed=1 means request is permitted

local key    = KEYS[1]
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])

local count = redis.call("INCR", key)
if count == 1 then
    redis.call("EXPIRE", key, window)
end

local allowed = 0
if count <= limit then
    allowed = 1
end

return {count, limit, allowed}
