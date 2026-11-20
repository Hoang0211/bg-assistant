from pathlib import Path
from typing import Literal

import pytest

from app.config import Settings, get_settings
from app.ingestion.elements import Element, ElementKind
from app.ingestion.parsers import DoclingParser, LlmParser, ParsedRulebook, create_parser
from app.llm.fake import FakeLLMProvider
from tests.helpers import make_pdf

MARKDOWN = "<!-- page 1 -->\n\n# Setup\n\nRoll the dice.\n"
ELEMENTS = [
    Element(ElementKind.HEADING, "Setup", 1),
    Element(ElementKind.PARAGRAPH, "Roll the dice.", 1),
]


async def test_llm_parser_writes_new_markdown_with_the_model(tmp_path: Path) -> None:
    path = tmp_path / "rules.pdf"
    path.write_bytes(make_pdf(1))
    llm = FakeLLMProvider(["# Setup\n\nRoll the dice."])

    parsed = await LlmParser(get_settings(), llm).parse(path, 1, None)

    assert parsed == ParsedRulebook(ELEMENTS, new_markdown=MARKDOWN)
    assert len(llm.calls) == 1


async def test_llm_parser_reuses_the_stored_markdown_without_the_model(tmp_path: Path) -> None:
    llm = FakeLLMProvider([])

    # No PDF at the path: a stored copy means the pages aren't even rendered.
    parsed = await LlmParser(get_settings(), llm).parse(tmp_path / "missing.pdf", 1, MARKDOWN)

    assert parsed == ParsedRulebook(ELEMENTS)  # no new Markdown to store
    assert llm.calls == []


@pytest.mark.parametrize(
    ("pdf_parser", "parser_class", "chunk_min_tokens"),
    [("docling", DoclingParser, 80), ("llm", LlmParser, 20)],
)
def test_create_parser_returns_the_chosen_parser_with_its_minimum(
    pdf_parser: Literal["docling", "llm"], parser_class: type[object], chunk_min_tokens: int
) -> None:
    settings = Settings(
        pdf_parser=pdf_parser,
        llm_provider="fake",
        chunk_min_tokens=80,
        markdown_chunk_min_tokens=20,
    )

    parser = create_parser(settings)

    assert isinstance(parser, parser_class)
    assert parser.chunk_min_tokens == chunk_min_tokens
