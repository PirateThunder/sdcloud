import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from redis.asyncio import Redis

from ..config import get_settings
from ..redis import fixed_window_limit


class RateLimited(Exception):
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class CodeMismatch(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_key(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()


def _code_hash(email: str, code: str) -> str:
    return hmac.new(
        get_settings().otp_secret.encode(), f"login:{email}:{code}".encode(), hashlib.sha256
    ).hexdigest()


async def request_code(redis: Redis, email: str, ip: str) -> str:
    settings = get_settings()
    digest = _email_key(email)
    cooldown_key = f"otp:cooldown:{digest}"
    cooldown = await redis.set(cooldown_key, "1", ex=settings.email_code_cooldown_seconds, nx=True)
    if not cooldown:
        ttl = await redis.ttl(cooldown_key)
        raise RateLimited("code already sent", max(1, ttl))

    date = datetime.now(UTC).strftime("%Y%m%d")
    if not await fixed_window_limit(
        redis, f"otp:daily-email:{digest}:{date}", settings.email_code_daily_per_email, 86400
    ):
        raise RateLimited("daily email limit exceeded", 3600)
    if not await fixed_window_limit(
        redis, f"otp:daily-ip:{ip}:{date}", settings.email_code_daily_per_ip, 86400
    ):
        raise RateLimited("daily IP limit exceeded", 3600)

    code = f"{secrets.randbelow(1_000_000):06d}"
    await redis.set(
        f"otp:code:{digest}", _code_hash(email, code), ex=settings.email_code_ttl_seconds
    )
    await redis.delete(f"otp:attempts:{digest}")
    return code


_VERIFY_SCRIPT = """
local stored = redis.call('GET', KEYS[1])
if not stored then return -1 end
local attempts = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[1], 'NX')
if stored ~= ARGV[3] then
  if attempts >= tonumber(ARGV[2]) then
    redis.call('DEL', KEYS[1], KEYS[2])
    return -2
  end
  return 0
end
redis.call('DEL', KEYS[1], KEYS[2])
return 1
"""


async def verify_code(redis: Redis, email: str, code: str, ip: str) -> None:
    settings = get_settings()
    if not await fixed_window_limit(
        redis, f"otp:verify-ip:{ip}", settings.email_code_verify_per_ip, 600
    ):
        raise RateLimited("too many verification attempts", 600)
    digest = _email_key(email)
    result = await redis.eval(
        _VERIFY_SCRIPT,
        2,
        f"otp:code:{digest}",
        f"otp:attempts:{digest}",
        settings.email_code_ttl_seconds,
        settings.email_code_max_attempts,
        _code_hash(email, code.strip()),
    )
    if result != 1:
        raise CodeMismatch("invalid or expired code")
