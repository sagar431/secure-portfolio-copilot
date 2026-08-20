from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.api.routes import system


@pytest.mark.asyncio
async def test_health_returns_success_envelope_and_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "test-request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert response.json() == {
        "data": {"status": "healthy"},
        "request_id": "test-request-123",
    }


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "unsafe request id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "unsafe request id"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_ready_returns_success_when_database_is_available(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = AsyncMock(return_value=True)
    monkeypatch.setattr(system, "check_database_ready", probe)

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ready"}
    probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_ready_fails_safely_when_database_is_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = AsyncMock(return_value=False)
    monkeypatch.setattr(system, "check_database_ready", probe)

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "service_unavailable",
        "message": "Service is not ready.",
    }
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
