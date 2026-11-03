import os
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent.parent / ".test_tmp"
TEST_ROOT.mkdir(exist_ok=True)
TEST_DB = TEST_ROOT / "api.sqlite"
TEST_DB.unlink(missing_ok=True)
os.environ.update(
    BACK_ENV="test",
    BACK_DATABASE_URL=f"sqlite+aiosqlite:///{TEST_DB}",
    BACK_REDIS_URL="redis://localhost:6399/15",
    BACK_EMAIL_DEV_CODE="1",
    BACK_POLL_INTERVAL_SECONDS="0",
    BACK_CORE_SUBMIT_TIMEOUT_SECONDS="1",
)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.main import app
from app.redis import get_redis
from app.registry import import_models

import_models()


@pytest.fixture
async def fake_redis():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: redis
    yield redis
    await redis.aclose()
    app.dependency_overrides.pop(get_redis, None)


@pytest.fixture(autouse=True)
async def database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
def no_queue_kicks(monkeypatch):
    async def no_kick(resource_id):
        return None

    monkeypatch.setattr("app.conversations.router.kick_generation", no_kick)
    monkeypatch.setattr("app.generations.router.kick_generation", no_kick)
    monkeypatch.setattr("app.simulations.router.kick_simulation", no_kick)


@pytest.fixture
async def client(fake_redis, database):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
