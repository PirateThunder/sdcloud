from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from ..config import get_settings
from ..database import DbDep, utc_now
from ..redis import RedisDep
from ..users.models import User
from ..users.schemas import UserOut
from . import email_code, sessions
from .dependencies import CurrentUser, check_origin, client_ip
from .email_sender import SendError, send_code
from .schemas import AuthPairOut, EmailRequestIn, EmailVerifyIn, OtpRequestOut
from .tokens import TokenError

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.refresh_cookie,
        refresh,
        max_age=settings.refresh_ttl_days * 86400,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.env not in {"local", "test"},
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.refresh_cookie,
        path=COOKIE_PATH,
        secure=settings.env not in {"local", "test"},
        samesite="lax",
    )


def _pair_out(user: User, access: str, expires_in: int) -> AuthPairOut:
    return AuthPairOut(
        user=UserOut.model_validate(user), access_token=access, expires_in=expires_in
    )


@router.post("/email/request", status_code=202, response_model=OtpRequestOut)
async def request_email_code(
    body: EmailRequestIn, request: Request, redis: RedisDep
) -> OtpRequestOut:
    email = email_code.normalize_email(body.email)
    try:
        code = await email_code.request_code(redis, email, client_ip(request))
    except email_code.RateLimited as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)}) from None
    try:
        await send_code(email, code)
    except SendError:
        raise HTTPException(503, "email service is temporarily unavailable") from None
    settings = get_settings()
    return OtpRequestOut(
        detail="if the address is valid, a login code has been sent",
        retry_after=settings.email_code_cooldown_seconds,
        dev_code=code if settings.email_dev_code and settings.env in {"local", "test"} else None,
    )


@router.post("/email/verify", response_model=AuthPairOut)
async def verify_email_code(
    body: EmailVerifyIn, request: Request, response: Response, db: DbDep, redis: RedisDep
) -> AuthPairOut:
    email = email_code.normalize_email(body.email)
    try:
        await email_code.verify_code(redis, email, body.code, client_ip(request))
    except email_code.RateLimited as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)}) from None
    except email_code.CodeMismatch:
        raise HTTPException(400, "invalid or expired code") from None

    user = await db.scalar(select(User).where(User.email == email))
    now = utc_now()
    if user is None:
        user = User(email=email, display_name=email.split("@", 1)[0][:200])
        db.add(user)
        await db.flush()
    if not user.is_active:
        raise HTTPException(403, "account is disabled")
    user.email_verified_at = user.email_verified_at or now
    user.last_login_at = now
    access, refresh, expires_in = await sessions.start_session(
        db,
        user,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:1000] or None,
    )
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return _pair_out(user, access, expires_in)


@router.post("/refresh", response_model=AuthPairOut)
async def refresh_session(request: Request, response: Response, db: DbDep) -> AuthPairOut:
    check_origin(request)
    token = request.cookies.get(get_settings().refresh_cookie)
    if not token:
        raise HTTPException(401, "refresh cookie is missing")
    try:
        user, access, refresh, expires_in = await sessions.rotate_session(
            db, token, ip_address=client_ip(request)
        )
    except TokenError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(401, str(exc)) from None
    _set_refresh_cookie(response, refresh)
    return _pair_out(user, access, expires_in)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DbDep) -> None:
    check_origin(request)
    await sessions.revoke_session(db, request.cookies.get(get_settings().refresh_cookie))
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
