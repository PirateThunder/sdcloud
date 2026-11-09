from app.config import get_settings
from tests.helpers import login


async def test_otp_login_normalizes_email_and_protects_routes(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/conversations")).status_code == 401
    assert (await client.post("/api/v1/guest/session")).status_code == 404

    headers = await login(client, "  User@Example.COM ")
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert me.json()["email_verified_at"] is not None
    assert "hashed_password" not in me.json()


async def test_otp_cooldown_single_use_and_fifth_attempt(client):
    requested = await client.post(
        "/api/v1/auth/email/request", json={"email": "person@example.com"}
    )
    code = requested.json()["dev_code"]
    duplicate = await client.post(
        "/api/v1/auth/email/request", json={"email": "person@example.com"}
    )
    assert duplicate.status_code == 429
    assert duplicate.headers["retry-after"]

    for _ in range(4):
        wrong = await client.post(
            "/api/v1/auth/email/verify",
            json={"email": "person@example.com", "code": "000000"},
        )
        assert wrong.status_code == 400
    verified = await client.post(
        "/api/v1/auth/email/verify", json={"email": "person@example.com", "code": code}
    )
    assert verified.status_code == 200
    replay = await client.post(
        "/api/v1/auth/email/verify", json={"email": "person@example.com", "code": code}
    )
    assert replay.status_code == 400


async def test_otp_is_destroyed_after_max_wrong_attempts(client):
    requested = await client.post(
        "/api/v1/auth/email/request", json={"email": "attempts@example.com"}
    )
    code = requested.json()["dev_code"]
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/email/verify",
            json={"email": "attempts@example.com", "code": "000000"},
        )
        assert response.status_code == 400
    correct = await client.post(
        "/api/v1/auth/email/verify", json={"email": "attempts@example.com", "code": code}
    )
    assert correct.status_code == 400


async def test_refresh_rotation_reuse_and_logout(client):
    await login(client, "refresh@example.com")
    cookie_name = get_settings().refresh_cookie
    old_refresh = client.cookies.get(cookie_name)

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new_refresh = client.cookies.get(cookie_name)
    assert new_refresh != old_refresh

    client.cookies.set(cookie_name, old_refresh, path="/api/v1/auth")
    reused = await client.post("/api/v1/auth/refresh")
    assert reused.status_code == 401

    client.cookies.set(cookie_name, new_refresh, path="/api/v1/auth")
    revoked = await client.post("/api/v1/auth/refresh")
    assert revoked.status_code == 401


async def test_logout_revokes_server_session_and_origin_is_checked(client):
    await login(client, "logout@example.com")
    forbidden = await client.post(
        "/api/v1/auth/refresh", headers={"Origin": "https://attacker.example"}
    )
    assert forbidden.status_code == 403

    logged_out = await client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 204
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 401


def test_production_requires_smtp_configuration():
    import pytest

    from app.config import Settings

    with pytest.raises(ValueError, match="BACK_SMTP_HOST"):
        Settings(
            env="production",
            jwt_secret="secret",
            otp_secret="other-secret",
            email_dev_code=False,
        )
    with pytest.raises(ValueError, match="BACK_SMTP_FROM or BACK_SMTP_USER"):
        Settings(
            env="production",
            jwt_secret="secret",
            otp_secret="other-secret",
            email_dev_code=False,
            smtp_host="smtp.example",
        )


def test_production_accepts_secure_otp_configuration():
    from app.config import Settings

    settings = Settings(
        env="production",
        jwt_secret="secret",
        otp_secret="other-secret",
        email_dev_code=False,
        smtp_host="smtp.example",
        smtp_from="sdcloud@example.com",
    )
    assert settings.smtp_host == "smtp.example"
    assert not settings.email_dev_code
