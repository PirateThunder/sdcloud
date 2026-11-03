import asyncio
import smtplib
from email.message import EmailMessage

from ..config import get_settings


class SendError(Exception):
    pass


def _send_sync(email: str, code: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = f"{code} — код входа в sdCloud"
    message["From"] = settings.smtp_from or settings.smtp_user or ""
    message["To"] = email
    minutes = settings.email_code_ttl_seconds // 60
    message.set_content(
        f"Ваш код входа в sdCloud: {code}\n\n"
        f"Код действует {minutes} минут. Если вы не запрашивали код, проигнорируйте письмо.\n"
    )
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
            ) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(message)
        else:
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
            ) as smtp:
                smtp.ehlo()
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise SendError("email delivery failed") from exc


async def send_code(email: str, code: str) -> None:
    settings = get_settings()
    if settings.email_dev_code and settings.env in {"local", "test"}:
        return
    if not settings.smtp_host:
        raise SendError("SMTP is not configured")
    await asyncio.to_thread(_send_sync, email, code)
