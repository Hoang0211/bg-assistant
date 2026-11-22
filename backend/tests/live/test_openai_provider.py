"""Calls the real OpenAI API, so it runs only with just test-live (a fraction of a cent)."""

import pymupdf
import pytest
from openai import AsyncOpenAI

from app.config import get_settings
from app.llm.base import ImagePart
from app.llm.openai import OpenAIProvider

pytestmark = pytest.mark.live


def _text_image(text: str) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page(width=300, height=80)
    page.insert_text((20, 45), text, fontsize=20)
    png: bytes = page.get_pixmap().tobytes("png")  # type: ignore[no-untyped-call]
    return png


async def test_openai_provider_reads_the_text_in_an_image() -> None:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0)

    completion = await OpenAIProvider(client).complete(
        settings.parser_model,
        "Copy the text in the image exactly, and output nothing else.",
        [ImagePart(_text_image("Players: 2-4"))],
        max_output_tokens=200,
        reasoning_effort="low",
    )

    assert completion.complete
    assert "Players: 2-4" in completion.text
    assert completion.usage.input_tokens > 0
