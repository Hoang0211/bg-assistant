from typing import Any

import pymupdf
from httpx2 import AsyncClient


def make_pdf(pages: int, **save_options: object) -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for _ in range(pages):
        doc.new_page()
    data: bytes = doc.tobytes(**save_options)  # type: ignore[no-untyped-call]
    return data


async def post_game(client: AsyncClient, **fields: object) -> dict[str, Any]:
    response = await client.post("/api/games", json={"name": "Game", **fields})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body
