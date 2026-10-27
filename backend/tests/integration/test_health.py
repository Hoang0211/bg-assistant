from httpx2 import AsyncClient

from app.api.deps import get_database_reachable
from app.main import app


async def test_health_returns_ok_when_db_reachable(client: AsyncClient) -> None:
    app.dependency_overrides[get_database_reachable] = lambda: True

    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_returns_503_when_db_unreachable(client: AsyncClient) -> None:
    app.dependency_overrides[get_database_reachable] = lambda: False

    response = await client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
