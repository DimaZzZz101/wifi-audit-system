"""Dependencies: DB session, current user, audit."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import async_session_maker
from app.models.user import User
from app.core.security import decode_access_token
from app.core.audit import log_audit

security = HTTPBearer(auto_error=False)


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User | None:
    if not credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError):
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    return user


async def require_user(
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def get_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def audit(
    db: AsyncSession,
    user_id: int | None,
    action: str,
    request: Request,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    await log_audit(
        db,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip=get_client_ip(request),
    )
