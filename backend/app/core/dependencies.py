"""FastAPI dependency injection providers."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_user_id_from_token
from app.core.exceptions import AuthenticationError
from app.db.session import get_db_session
from app.models.user import User

security = HTTPBearer(auto_error=False)


async def get_db() -> AsyncSession:
    """Dependency that provides an async database session."""
    async for session in get_db_session():
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that resolves the current authenticated user from a JWT token."""
    if credentials is None:
        raise AuthenticationError(detail="Authorization header required")

    token = credentials.credentials
    user_id = get_user_id_from_token(token)

    if user_id is None:
        raise AuthenticationError(detail="Invalid or expired token")

    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise AuthenticationError(detail="User not found")

    if not user.is_active:
        raise AuthenticationError(detail="User account is deactivated")

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency that ensures the user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user
