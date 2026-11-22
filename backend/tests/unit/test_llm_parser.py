from pathlib import Path

import pymupdf
import pytest

from app.config import Settings, get_settings
from app.ingestion.llm_parser import TruncatedPageError, parse_pdf_to_markdown
from app.ingestion.pdf_info import render_page
from app.llm.base import Completion, ImagePart, Usage
from app.llm.fake import FakeLLMProvider
from tests.helpers import add_text_page

SETTINGS = get_settings()


def _two_page_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", ["Each player takes 5 cards."])
    add_text_page(doc, "Scoring", ["The player with the most points wins."])
    path = tmp_path / "rules.pdf"
    doc.save(path)  # type: ignore[no-untyped-call]
    return path


async def test_parse_pdf_to_markdown_writes_each_page_after_its_marker(tmp_path: Path) -> None:
    llm = FakeLLMProvider(["# Setup\n\nEach player takes 5 cards.\n", "# Scoring"])

    markdown = await parse_pdf_to_markdown(_two_page_pdf(tmp_path), 2, llm, SETTINGS)

    assert markdown == (
        "<!-- page 1 -->\n\n# Setup\n\nEach player takes 5 cards.\n\n<!-- page 2 -->\n\n# Scoring\n"
    )


@pytest.mark.parametrize(
    "reply", ["```markdown\n# Setup\n\nRoll.\n```", "```\n# Setup\n\nRoll.\n```\n"]
)
async def test_parse_pdf_to_markdown_removes_a_code_fence_around_a_reply(
    tmp_path: Path, reply: str
) -> None:
    llm = FakeLLMProvider([reply, "# Scoring"])

    markdown = await parse_pdf_to_markdown(_two_page_pdf(tmp_path), 2, llm, SETTINGS)

    assert markdown == "<!-- page 1 -->\n\n# Setup\n\nRoll.\n\n<!-- page 2 -->\n\n# Scoring\n"


async def test_parse_pdf_to_markdown_keeps_a_code_fence_inside_a_reply(tmp_path: Path) -> None:
    reply = "# Setup\n\n```\nnot the whole reply\n```\n\nRoll."
    llm = FakeLLMProvider([reply, "# Scoring"])

    markdown = await parse_pdf_to_markdown(_two_page_pdf(tmp_path), 2, llm, SETTINGS)

    assert markdown == f"<!-- page 1 -->\n\n{reply}\n\n<!-- page 2 -->\n\n# Scoring\n"


async def test_parse_pdf_to_markdown_keeps_the_marker_of_a_page_with_no_text(
    tmp_path: Path,
) -> None:
    llm = FakeLLMProvider(["# Setup", " \n"])

    markdown = await parse_pdf_to_markdown(_two_page_pdf(tmp_path), 2, llm, SETTINGS)

    assert markdown == "<!-- page 1 -->\n\n# Setup\n\n<!-- page 2 -->\n"


async def test_parse_pdf_to_markdown_sends_each_page_image_with_the_parser_settings(
    tmp_path: Path,
) -> None:
    path = _two_page_pdf(tmp_path)
    llm = FakeLLMProvider(["# Setup", "# Scoring"])
    # Not the defaults, so the call can only match if it uses the settings it's given.
    settings = Settings(
        parser_model="parser",
        parser_max_output_tokens=123,
        parser_reasoning_effort="none",
        parser_image_px=600,
    )

    await parse_pdf_to_markdown(path, 2, llm, settings)

    assert [call.parts for call in llm.calls] == [
        [ImagePart(render_page(path, page, settings.parser_image_px))] for page in (1, 2)
    ]
    assert [(call.model, call.max_output_tokens, call.reasoning_effort) for call in llm.calls] == [
        (settings.parser_model, settings.parser_max_output_tokens, settings.parser_reasoning_effort)
    ] * 2
    # The same instructions on every call: only the page image changes.
    assert llm.calls[0].instructions == llm.calls[1].instructions != ""


async def test_parse_pdf_to_markdown_stops_at_a_cut_off_page(tmp_path: Path) -> None:
    cap = SETTINGS.parser_max_output_tokens
    cut_off = Completion("# Setup\n\nEach player", complete=False, usage=Usage(3000, 0, cap, 0))
    llm = FakeLLMProvider([cut_off, "# Scoring"])

    with pytest.raises(TruncatedPageError, match=f"page 1's Markdown was cut off at {cap} "):
        await parse_pdf_to_markdown(_two_page_pdf(tmp_path), 2, llm, SETTINGS)

    assert len(llm.calls) == 1  # page 2 is never sent, so never paid for
