"""Authentication endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AuthenticationError, ConflictError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    TokenPair,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Create a new user account with email, username, and password."""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise ConflictError(detail="Email already registered")

    # Check if username already exists
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise ConflictError(detail="Username already taken")

    # Create user
    user = User(
        email=data.email,
        username=data.username,
        hashed_password=get_password_hash(data.password),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Login with username and password",
)
async def login(
    data: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Authenticate user and return JWT access + refresh tokens."""
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    if user is None:
        raise AuthenticationError(detail="Invalid username or password")

    if not verify_password(data.password, user.hashed_password):
        raise AuthenticationError(detail="Invalid username or password")

    if not user.is_active:
        raise AuthenticationError(detail="Account is deactivated")

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Refresh access token using refresh token",
)
async def refresh_token(
    data: dict,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Exchange a valid refresh token for a new access token pair."""
    from app.core.security import decode_token, get_user_id_from_token

    refresh_token = data.get("refresh_token", "")
    payload = decode_token(refresh_token)

    if payload is None:
        raise AuthenticationError(detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise AuthenticationError(detail="Invalid token type")

    user_id = get_user_id_from_token(refresh_token)
    if user_id is None:
        raise AuthenticationError(detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise AuthenticationError(detail="User not found or inactive")

    new_access = create_access_token(user.id)
    new_refresh = create_refresh_token(user.id)

    return TokenPair(
        access_token=new_access,
        refresh_token=new_refresh,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the currently authenticated user's profile."""
    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Update the current user's profile information."""
    if data.email is not None:
        # Check email uniqueness
        result = await db.execute(
            select(User).where(User.email == data.email, User.id != current_user.id)
        )
        if result.scalar_one_or_none():
            raise ConflictError(detail="Email already in use")
        current_user.email = data.email

    if data.username is not None:
        result = await db.execute(
            select(User).where(User.username == data.username, User.id != current_user.id)
        )
        if result.scalar_one_or_none():
            raise ConflictError(detail="Username already taken")
        current_user.username = data.username

    await db.commit()
    await db.refresh(current_user)
    return current_user
