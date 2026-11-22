from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.ingestion.elements import Element, ElementKind
from app.ingestion.parsers import LlmParser, ParsedRulebook
from app.llm.fake import FakeLLMProvider
from tests.helpers import make_pdf

MARKDOWN = "<!-- page 1 -->\n\n# Setup\n\nRoll the dice.\n"
ELEMENTS = [
    Element(ElementKind.HEADING, "Setup", 1),
    Element(ElementKind.PARAGRAPH, "Roll the dice.", 1),
]

# Settings that would make the OpenAI provider, which refuses to be created without a key.
NO_KEY = Settings(llm_provider="openai", openai_api_key=SecretStr(""))


async def test_llm_parser_writes_new_markdown_with_the_model(tmp_path: Path) -> None:
    path = tmp_path / "rules.pdf"
    path.write_bytes(make_pdf(1))
    llm = FakeLLMProvider(["# Setup\n\nRoll the dice."])

    parsed = await LlmParser(get_settings(), llm).parse(path, 1, None)

    assert parsed == ParsedRulebook(ELEMENTS, new_markdown=MARKDOWN)
    assert len(llm.calls) == 1


async def test_llm_parser_calls_the_model_with_its_own_settings(tmp_path: Path) -> None:
    path = tmp_path / "rules.pdf"
    path.write_bytes(make_pdf(1))
    llm = FakeLLMProvider(["# Setup"])
    settings = Settings(parser_model="parser", parser_max_output_tokens=123)

    await LlmParser(settings, llm).parse(path, 1, None)

    assert [(call.model, call.max_output_tokens) for call in llm.calls] == [("parser", 123)]


async def test_llm_parser_reuses_the_stored_markdown_without_the_model(tmp_path: Path) -> None:
    llm = FakeLLMProvider([])

    # No PDF at the path: a stored copy means the pages aren't even rendered.
    parsed = await LlmParser(get_settings(), llm).parse(tmp_path / "missing.pdf", 1, MARKDOWN)

    assert parsed == ParsedRulebook(ELEMENTS)  # no new Markdown to store
    assert llm.calls == []


async def test_llm_parser_reads_stored_markdown_without_an_api_key(tmp_path: Path) -> None:
    parsed = await LlmParser(NO_KEY).parse(tmp_path / "missing.pdf", 1, MARKDOWN)

    assert parsed == ParsedRulebook(ELEMENTS)


async def test_llm_parser_needs_an_api_key_only_to_call_the_model(tmp_path: Path) -> None:
    path = tmp_path / "rules.pdf"
    path.write_bytes(make_pdf(1))

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await LlmParser(NO_KEY).parse(path, 1, None)
