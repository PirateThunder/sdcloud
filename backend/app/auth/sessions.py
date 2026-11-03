import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import utc_now
from ..users.models import User
from .models import AuthSession
from .tokens import TokenError, hashes_match, issue_access, new_refresh_secret, refresh_hash


def _session_id(token: str) -> uuid.UUID:
    try:
        raw_id, secret = token.split(".", 1)
        if not secret:
            raise ValueError
        return uuid.UUID(raw_id)
    except (ValueError, AttributeError) as exc:
        raise TokenError("invalid refresh token") from exc


async def start_session(
    db: AsyncSession,
    user: User,
    *,
    ip_address: str,
    user_agent: str | None,
) -> tuple[str, str, int]:
    session_id = uuid.uuid4()
    refresh = f"{session_id}.{new_refresh_secret()}"
    auth_session = AuthSession(
        id=session_id,
        user_id=user.id,
        refresh_hash=refresh_hash(refresh),
        expires_at=utc_now() + timedelta(days=get_settings().refresh_ttl_days),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(auth_session)
    await db.flush()
    access, expires_in = issue_access(user, session_id)
    return access, refresh, expires_in


async def rotate_session(
    db: AsyncSession,
    token: str,
    *,
    ip_address: str,
) -> tuple[User, str, str, int]:
    session_id = _session_id(token)
    auth_session = await db.scalar(
        select(AuthSession).where(AuthSession.id == session_id).with_for_update()
    )
    now = utc_now()
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
    ):
        raise TokenError("refresh session is invalid or expired")
    if not hashes_match(auth_session.refresh_hash, refresh_hash(token)):
        auth_session.revoked_at = now
        auth_session.last_used_at = now
        await db.commit()
        raise TokenError("refresh token reuse detected")
    user = await db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise TokenError("refresh session owner is unavailable")
    refresh = f"{auth_session.id}.{new_refresh_secret()}"
    auth_session.refresh_hash = refresh_hash(refresh)
    auth_session.rotated_at = now
    auth_session.last_used_at = now
    auth_session.ip_address = ip_address
    access, expires_in = issue_access(user, auth_session.id)
    await db.commit()
    return user, access, refresh, expires_in


async def revoke_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    try:
        session_id = _session_id(token)
    except TokenError:
        return
    auth_session = await db.scalar(
        select(AuthSession).where(AuthSession.id == session_id).with_for_update()
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return
    if hashes_match(auth_session.refresh_hash, refresh_hash(token)):
        auth_session.revoked_at = utc_now()
        await db.commit()
