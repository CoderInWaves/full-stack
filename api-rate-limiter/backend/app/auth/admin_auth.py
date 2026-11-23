"""Admin token authentication."""
from fastapi import HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.settings import settings

bearer_scheme = HTTPBearer(auto_error=False)


async def require_admin(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
):
    token = credentials.credentials if credentials else None
    if not token or token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": "Invalid or missing admin token"},
        )
    return token
