import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from ..config import get_settings
from ..users.models import User


class TokenError(Exception):
    pass


def issue_access(user: User, session_id: uuid.UUID) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_ttl_minutes * 60
    payload = {
        "sub": str(user.id),
        "sid": str(session_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expires_in


def verify_access(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise TokenError("invalid token type")
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["sid"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise TokenError("invalid or expired access token") from exc


def new_refresh_secret() -> str:
    return secrets.token_urlsafe(32)


def refresh_hash(token: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def hashes_match(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
