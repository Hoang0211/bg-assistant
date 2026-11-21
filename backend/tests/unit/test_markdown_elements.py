import pytest

from app.db.models import ChunkType
from app.ingestion.chunker import ChunkLimits, TextChunk, chunk_elements
from app.ingestion.elements import Element, ElementKind
from app.ingestion.markdown_elements import markdown_to_elements, split_pages


def test_markdown_to_elements_reads_each_block_on_its_page() -> None:
    markdown = (
        "<!-- page 1 -->\n\n# Setup\n\nPlace the board.\n\n"
        "<!-- page 2 -->\n\n# Trading\n\n- Trade with the bank.\n- Trade with players.\n\n"
        "| Building | Cost |\n|---|---|\n| Road | Brick |\n"
    )

    assert markdown_to_elements(markdown) == [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
        Element(ElementKind.HEADING, "Trading", 2),
        Element(ElementKind.LIST_ITEM, "- Trade with the bank.", 2),
        Element(ElementKind.LIST_ITEM, "- Trade with players.", 2),
        Element(ElementKind.TABLE, "| Building | Cost |\n|---|---|\n| Road | Brick |", 2),
    ]


def test_markdown_to_elements_builds_each_heading_path_from_the_levels() -> None:
    markdown = "## Setup\n\n### Market\n\n## Turn\n\n#### Trading\n\n### Bonus\n\n# Variants\n"

    headings = [element.text for element in markdown_to_elements(markdown)]

    assert headings == [
        "Setup",
        "Setup › Market",
        "Turn",
        "Turn › Trading",
        "Turn › Bonus",
        "Variants",
    ]


def test_markdown_to_elements_reads_a_heading_followed_by_text_on_the_next_line() -> None:
    assert markdown_to_elements("## Setup\nPlace the board.\n") == [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
    ]


def test_markdown_to_elements_keeps_a_nested_list_with_its_item() -> None:
    markdown = "- Say STOP.\n- Say LAST CHANCE.\n  - Bet won: score your cards.\n  - Bet lost.\n"

    assert markdown_to_elements(markdown) == [
        Element(ElementKind.LIST_ITEM, "- Say STOP.", 1),
        Element(
            ElementKind.LIST_ITEM,
            "- Say LAST CHANCE.\n  - Bet won: score your cards.\n  - Bet lost.",
            1,
        ),
    ]


def test_markdown_to_elements_reads_a_numbered_list() -> None:
    assert markdown_to_elements("1. Roll the dice.\n2. Trade.\n") == [
        Element(ElementKind.LIST_ITEM, "1. Roll the dice.", 1),
        Element(ElementKind.LIST_ITEM, "2. Trade.", 1),
    ]


def test_markdown_to_elements_keeps_a_blockquote_as_a_paragraph() -> None:
    markdown = "> **Example:** Anna rolls a 7.\n>\n> She moves the robber.\n"

    assert markdown_to_elements(markdown) == [
        Element(
            ElementKind.PARAGRAPH, "> **Example:** Anna rolls a 7.\n>\n> She moves the robber.", 1
        )
    ]


def test_markdown_to_elements_reads_a_bold_line_as_a_caption() -> None:
    assert markdown_to_elements("**Odds for Dice Rolls**\n") == [
        Element(ElementKind.CAPTION, "**Odds for Dice Rolls**", 1)
    ]


@pytest.mark.parametrize(
    "text", ["**Example:** Anna rolls a 7.", "**Roads** and **cities**", "**Setup**\n**Trading**"]
)
def test_markdown_to_elements_keeps_a_partly_bold_block_as_a_paragraph(text: str) -> None:
    assert markdown_to_elements(f"{text}\n") == [Element(ElementKind.PARAGRAPH, text, 1)]


def test_markdown_to_elements_continues_the_section_on_a_page_with_no_heading() -> None:
    markdown = (
        "<!-- page 3 -->\n\n## Setup\n\nPlace the board.\n\n<!-- page 4 -->\n\nShuffle the cards.\n"
    )

    assert markdown_to_elements(markdown) == [
        Element(ElementKind.HEADING, "Setup", 3),
        Element(ElementKind.PARAGRAPH, "Place the board.", 3),
        Element(ElementKind.HEADING, "Setup", 4),
        Element(ElementKind.PARAGRAPH, "Shuffle the cards.", 4),
    ]


def test_markdown_to_elements_joins_a_sentence_cut_by_a_page_break() -> None:
    markdown = (
        "<!-- page 3 -->\n\n## Setup\n\nEach player draws two cards and\n\n"
        "<!-- page 4 -->\n\nplaces one face down.\n\nThen the game starts.\n"
    )

    assert markdown_to_elements(markdown) == [
        Element(ElementKind.HEADING, "Setup", 3),
        Element(
            ElementKind.PARAGRAPH,
            "Each player draws two cards and places one face down.",
            3,
            last_page=4,
        ),
        Element(ElementKind.HEADING, "Setup", 4),
        Element(ElementKind.PARAGRAPH, "Then the game starts.", 4),
    ]


def test_markdown_to_elements_adds_no_path_to_a_page_that_starts_with_a_heading() -> None:
    markdown = "<!-- page 3 -->\n\n## Setup\n\nPlace the board.\n\n<!-- page 4 -->\n\n## Trading\n"

    assert markdown_to_elements(markdown) == [
        Element(ElementKind.HEADING, "Setup", 3),
        Element(ElementKind.PARAGRAPH, "Place the board.", 3),
        Element(ElementKind.HEADING, "Trading", 4),
    ]


def test_markdown_to_elements_continues_the_section_after_a_blank_page() -> None:
    markdown = (
        "<!-- page 3 -->\n\n## Setup\n\nPlace the board.\n\n<!-- page 4 -->\n\n"
        "<!-- page 5 -->\n\nShuffle the cards.\n"
    )

    assert markdown_to_elements(markdown)[2:] == [
        Element(ElementKind.HEADING, "Setup", 5),
        Element(ElementKind.PARAGRAPH, "Shuffle the cards.", 5),
    ]


def test_markdown_to_elements_adds_no_heading_before_the_first_one() -> None:
    markdown = "<!-- page 1 -->\n\nA game for 2 players.\n\n<!-- page 2 -->\n\nAges 8 and up.\n"

    assert markdown_to_elements(markdown) == [
        Element(ElementKind.PARAGRAPH, "A game for 2 players.", 1),
        Element(ElementKind.PARAGRAPH, "Ages 8 and up.", 2),
    ]


def test_markdown_to_elements_returns_nothing_for_no_text() -> None:
    assert markdown_to_elements("<!-- page 1 -->\n\n<!-- page 2 -->\n") == []


def test_markdown_to_elements_gives_the_chunker_one_chunk_per_page_of_a_section() -> None:
    markdown = (
        "<!-- page 3 -->\n\n## Setup\n\n### Market\n\nPlace the board.\n\n"
        "<!-- page 4 -->\n\nShuffle the cards.\n"
    )
    limits = ChunkLimits(min_tokens=0, target_tokens=1000, max_tokens=1000, overlap_tokens=0)

    chunks = chunk_elements(markdown_to_elements(markdown), lambda text: len(text.split()), limits)

    assert chunks == [
        TextChunk(
            section_path="Setup › Market",
            chunk_type=ChunkType.SECTION,
            page_start=3,
            page_end=3,
            content="Setup › Market\n\nPlace the board.",
        ),
        TextChunk(
            section_path="Setup › Market",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=4,
            content="Setup › Market\n\nShuffle the cards.",
        ),
    ]


def test_markdown_to_elements_gives_the_chunker_a_tables_caption() -> None:
    markdown = (
        "## Setup\n\nPlace the board.\n\n**Odds for Dice Rolls**\n\n"
        "| Roll | Odds |\n|---|---|\n| 6 & 8 | 14% |\n"
    )
    limits = ChunkLimits(min_tokens=0, target_tokens=1000, max_tokens=1000, overlap_tokens=0)

    chunks = chunk_elements(markdown_to_elements(markdown), lambda text: len(text.split()), limits)

    assert [chunk.content for chunk in chunks] == [
        "Setup\n\nPlace the board.",
        "Setup\n\n**Odds for Dice Rolls**\n\n| Roll | Odds |\n|---|---|\n| 6 & 8 | 14% |",
    ]


def test_split_pages_returns_each_pages_markdown_by_number() -> None:
    markdown = "<!-- page 1 -->\n\n# Setup\n\n<!-- page 2 -->\n\n<!-- page 3 -->\n\nTrade.\n"

    assert split_pages(markdown) == {1: "\n\n# Setup\n\n", 2: "\n\n", 3: "\n\nTrade.\n"}


def test_split_pages_drops_text_before_the_first_page() -> None:
    assert split_pages("Cover\n\n<!-- page 1 -->\n\nSetup\n") == {1: "\n\nSetup\n"}
