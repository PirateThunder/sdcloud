"""Pytest configuration and shared fixtures."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import get_password_hash
from app.db.base import Base
from app.main import app
from app.models.user import User

# Use an in-memory SQLite database for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Create async engine for tests
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
    echo=False,
)

# Create test session factory
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create the test database engine and tables."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Create a fresh database session for each test."""
    async with TestSessionLocal() as session:
        yield session
        # Clean up after test
        await session.rollback()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("testpassword"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def client():
    """Create a test client."""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    """Get authorization headers for the test user."""
    from app.core.security import create_access_token

    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}
