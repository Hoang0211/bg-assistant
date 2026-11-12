from typing import Any

import pymupdf
from httpx2 import AsyncClient


def make_pdf(pages: int, **save_options: object) -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for _ in range(pages):
        doc.new_page()
    data: bytes = doc.tobytes(**save_options)  # type: ignore[no-untyped-call]
    return data


def add_text_page(
    doc: pymupdf.Document,
    heading: str,
    paragraphs: list[str],
    bullets: list[str] | None = None,
    header: str | None = None,
    page_number: int | None = None,
) -> pymupdf.Page:
    page = doc.new_page()
    if header is not None:
        page.insert_text((72, 40), header, fontsize=8)
    page.insert_text((72, 72), heading, fontsize=20, fontname="hebo")
    y = 92
    for paragraph in paragraphs:
        box = pymupdf.Rect(72, y, 523, y + 60)  # type: ignore[no-untyped-call]
        space_left = page.insert_textbox(box, paragraph, fontsize=11)
        assert space_left >= 0, f"paragraph too long for its box: {paragraph!r}"
        y += 60
    for bullet in bullets or []:
        page.insert_text((90, y), f"\u2022 {bullet}", fontsize=11)
        y += 18
    if page_number is not None:
        page.insert_text((290, 800), str(page_number), fontsize=9)
    return page


async def post_game(client: AsyncClient, **fields: object) -> dict[str, Any]:
    response = await client.post("/api/games", json={"name": "Game", **fields})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body
