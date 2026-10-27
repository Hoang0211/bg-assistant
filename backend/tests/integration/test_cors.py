from httpx2 import AsyncClient

from app.api.deps import get_database_reachable
from app.main import app


async def test_cors_allows_frontend_origin(client: AsyncClient) -> None:
    app.dependency_overrides[get_database_reachable] = lambda: True
    origin = "http://localhost:3000"
    response = await client.get("/api/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


async def test_cors_blocks_other_origin(client: AsyncClient) -> None:
    app.dependency_overrides[get_database_reachable] = lambda: True
    origin = "http://evil.example"
    response = await client.get("/api/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") is None
