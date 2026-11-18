"""Parses a generated page with the real model, so it runs only with just test-live (a cent)."""

import re
from pathlib import Path

import pymupdf
import pytest
from openai import AsyncOpenAI

from app.config import get_settings
from app.ingestion.llm_parser import parse_pdf_to_markdown
from app.llm.openai import OpenAIProvider
from tests.helpers import add_text_page

pytestmark = pytest.mark.live


async def test_parse_pdf_to_markdown_writes_the_heading_and_the_text(tmp_path: Path) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", ["Each player takes 5 cards and places them face down."])
    path = tmp_path / "rules.pdf"
    doc.save(path)  # type: ignore[no-untyped-call]
    api_key = get_settings().openai_api_key.get_secret_value()
    llm = OpenAIProvider(AsyncOpenAI(api_key=api_key, max_retries=0))

    markdown = await parse_pdf_to_markdown(path, 1, llm)

    lines = markdown.splitlines()
    assert lines[0] == "<!-- page 1 -->"
    assert any(re.fullmatch(r"#{1,3} Setup", line) for line in lines)
    assert "Each player takes 5 cards and places them face down." in markdown
