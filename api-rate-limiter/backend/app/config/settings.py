import os
from pydantic import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_password: str = os.getenv("REDIS_PASSWORD", "")

    # Gateway
    gateway_id: str = os.getenv("GATEWAY_ID", "gateway-1")
    demo_backend_url: str = os.getenv("DEMO_BACKEND_URL", "http://localhost:8001")

    # Admin
    admin_token: str = os.getenv("ADMIN_TOKEN", "dev-admin-token-change-in-production")

    # Rate limiting defaults
    default_limit: int = int(os.getenv("DEFAULT_LIMIT", "10"))
    default_window: int = int(os.getenv("DEFAULT_WINDOW", "60"))
    default_algorithm: str = os.getenv("DEFAULT_ALGORITHM", "sliding_window")

    # Behavior on Redis failure
    fail_open: bool = os.getenv("FAIL_OPEN", "false").lower() == "true"

    # CORS
    cors_origins: list = ["http://localhost:3000", "http://localhost:5173", "http://localhost:8080"]

    class Config:
        env_file = ".env"


settings = Settings()
