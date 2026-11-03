from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from ..database import DbDep
from ..users.models import User
from .tokens import TokenError, verify_access

_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:100]
    return (request.client.host if request.client else "unknown")[:100]


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in get_settings().cors_origin_list:
        raise HTTPException(403, "origin is not allowed")


async def current_user(
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)] = None,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer access token is required")
    try:
        user_id, _ = verify_access(credentials.credentials)
    except TokenError:
        raise HTTPException(401, "access token is invalid or expired") from None
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "token owner is not found")
    if not user.is_active:
        raise HTTPException(403, "account is disabled")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
