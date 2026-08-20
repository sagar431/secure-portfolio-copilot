import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_unknown_route_uses_safe_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    assert response.json()["error"] == {"code": "not_found", "message": "Not Found"}
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_unhandled_exception_does_not_leak_details() -> None:
    test_app: FastAPI = create_app()

    @test_app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("sensitive-database-detail")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/explode")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "Internal server error.",
    }
    assert "sensitive-database-detail" not in response.text
