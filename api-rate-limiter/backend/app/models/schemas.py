from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import time


class Algorithm(str, Enum):
    fixed_window = "fixed_window"
    sliding_window = "sliding_window"
    token_bucket = "token_bucket"


class ClientTier(str, Enum):
    basic = "basic"
    premium = "premium"


# ── API Client ────────────────────────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str
    tier: ClientTier = ClientTier.basic


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    tier: Optional[ClientTier] = None
    enabled: Optional[bool] = None


class ClientResponse(BaseModel):
    id: str
    name: str
    tier: ClientTier
    enabled: bool
    created_at: float
    key_prefix: str          # first 8 chars of key for display
    total_requests: int = 0
    rejected_requests: int = 0


class ClientCreateResponse(ClientResponse):
    api_key: str             # shown only once at creation


# ── Rate-Limit Policy ─────────────────────────────────────────────────────────

class PolicyCreate(BaseModel):
    client_id: Optional[str] = None          # None = global default
    method: Optional[str] = None             # None = all methods
    route: Optional[str] = None              # None = all routes
    algorithm: Algorithm = Algorithm.sliding_window
    limit: int = Field(default=10, ge=1)
    window: int = Field(default=60, ge=1)    # seconds
    bucket_capacity: Optional[int] = None   # token bucket
    refill_rate: Optional[float] = None     # tokens/second
    enabled: bool = True


class PolicyUpdate(BaseModel):
    algorithm: Optional[Algorithm] = None
    limit: Optional[int] = Field(default=None, ge=1)
    window: Optional[int] = Field(default=None, ge=1)
    bucket_capacity: Optional[int] = None
    refill_rate: Optional[float] = None
    enabled: Optional[bool] = None


class PolicyResponse(PolicyCreate):
    id: str
    created_at: float
    updated_at: float


# ── Rate-Limit Result ─────────────────────────────────────────────────────────

class RateLimitResult(BaseModel):
    allowed: bool
    limit: int
    remaining: int
    retry_after: int         # seconds until next allowed request
    reset_at: float          # unix timestamp when window resets
    algorithm: str


# ── Analytics ─────────────────────────────────────────────────────────────────

class OverviewStats(BaseModel):
    total_requests: int
    allowed_requests: int
    rejected_requests: int
    total_clients: int
    active_policies: int
    requests_per_second: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


class TimeSeriesPoint(BaseModel):
    timestamp: float
    total: int
    allowed: int
    rejected: int


class RouteStats(BaseModel):
    route: str
    total: int
    allowed: int
    rejected: int


class ClientStats(BaseModel):
    client_id: str
    client_name: str
    total: int
    rejected: int


class AnalyticsResponse(BaseModel):
    time_series: List[TimeSeriesPoint]
    by_route: List[RouteStats]
    by_client: List[ClientStats]
    by_algorithm: dict


# ── Health ────────────────────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    name: str
    status: str              # "healthy" | "degraded" | "down"
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    overall: str
    gateway_id: str
    uptime_seconds: float
    services: List[ServiceHealth]


# ── Admin Auth ────────────────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    token: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
