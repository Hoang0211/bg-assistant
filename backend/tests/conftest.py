from collections.abc import AsyncIterator, Iterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client that sends requests straight to the FastAPI app, without starting a server."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Iterator[None]:
    """Remove any dependency overrides a test set, so they can't leak into the next test."""
    yield
    app.dependency_overrides.clear()
