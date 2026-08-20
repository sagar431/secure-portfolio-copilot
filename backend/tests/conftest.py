import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app, create_app
from app.scripts.seed_development import seed_database

DEMO_PASSWORD = "Step2IntegrationPassword-2026"


@dataclass(frozen=True)
class AuthHarness:
    client: AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest_asyncio.fixture
async def auth_harness(tmp_path: Path) -> AsyncIterator[AuthHarness]:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://portfolio:portfolio_test@127.0.0.1:5433/portfolio_test",
    )
    if make_url(database_url).database != "portfolio_test":
        raise RuntimeError("Integration tests require a database named portfolio_test")

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        jwt_secret_key=SecretStr("integration-test-jwt-key-with-at-least-thirty-two-characters"),
        jwt_issuer="integration-test-issuer",
        jwt_audience="integration-test-audience",
        demo_user_password=SecretStr(DEMO_PASSWORD),
        document_storage_path=tmp_path / "document-storage",
        embedding_provider="fake",
    )
    test_engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        await seed_database(session, DEMO_PASSWORD)

    test_app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    test_app.dependency_overrides[get_db_session] = override_session
    test_app.dependency_overrides[get_settings] = lambda: settings
    transport = ASGITransport(app=test_app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield AuthHarness(
                client=test_client,
                session_factory=session_factory,
                settings=settings,
            )
    finally:
        test_app.dependency_overrides.clear()
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()
