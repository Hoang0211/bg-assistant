from app.db.models import ChunkType
from app.ingestion.chunker import TextChunk, chunk_elements
from app.ingestion.layout_parser import Element, ElementKind


def count_words(text: str) -> int:
    return len(text.split())


def test_chunk_elements_starts_a_new_chunk_at_each_heading() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.LIST_ITEM, "Trade with the bank.", 1),
    ]

    assert chunk_elements(elements, count_words, min_tokens=0) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Setup\n\nPlace the board.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\nTrade with the bank.",
        ),
    ]


def test_chunk_elements_covers_every_page_of_a_section() -> None:
    elements = [
        Element(ElementKind.HEADING, "Trading", 2),
        Element(ElementKind.PARAGRAPH, "Trade with the bank.", 3),
        Element(ElementKind.PARAGRAPH, "Trade with other players.", 4),
    ]

    assert chunk_elements(elements, count_words, min_tokens=0) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=4,
            content="Trading\n\nTrade with the bank.\n\nTrade with other players.",
        )
    ]


def test_chunk_elements_keeps_text_before_the_first_heading() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Welcome to the game.", 1),
        Element(ElementKind.HEADING, "Setup", 2),
        Element(ElementKind.PARAGRAPH, "Place the board.", 2),
    ]

    assert chunk_elements(elements, count_words, min_tokens=0) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Welcome to the game.",
        ),
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=2,
            content="Setup\n\nPlace the board.",
        ),
    ]


def test_chunk_elements_skips_a_heading_with_no_text() -> None:
    elements = [
        Element(ElementKind.HEADING, "Turn Order", 1),
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.PARAGRAPH, "Trade with the bank.", 1),
    ]

    assert chunk_elements(elements, count_words, min_tokens=0) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\nTrade with the bank.",
        )
    ]


def test_chunk_elements_returns_nothing_for_no_elements() -> None:
    assert chunk_elements([], count_words, min_tokens=0) == []


def test_chunk_elements_merges_a_small_section_into_the_previous_one() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board now.", 1),
        Element(ElementKind.HEADING, "Illustration A", 2),
        Element(ElementKind.PARAGRAPH, "See here.", 2),
    ]

    assert chunk_elements(elements, count_words, min_tokens=5) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=2,
            content="Setup\n\nPlace the board now.\n\nIllustration A\n\nSee here.",
        ),
    ]


def test_chunk_elements_merges_a_small_first_section_into_the_next_one() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Welcome", 1),
        Element(ElementKind.HEADING, "Setup", 2),
        Element(ElementKind.PARAGRAPH, "Place the board on the table.", 2),
    ]

    assert chunk_elements(elements, count_words, min_tokens=5) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=2,
            content="Setup\n\nWelcome\n\nPlace the board on the table.",
        ),
    ]


def test_chunk_elements_keeps_a_section_at_the_limit() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
        Element(ElementKind.HEADING, "Trading", 2),
        Element(ElementKind.PARAGRAPH, "Trade with banks.", 2),
    ]

    assert chunk_elements(elements, count_words, min_tokens=4) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Setup\n\nPlace the board.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=2,
            content="Trading\n\nTrade with banks.",
        ),
    ]


def test_chunk_elements_keeps_a_lone_small_section() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
    ]

    assert chunk_elements(elements, count_words, min_tokens=80) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Setup\n\nPlace the board.",
        ),
    ]


def test_chunk_elements_merges_consecutive_small_sections_into_one() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board now.", 1),
        Element(ElementKind.HEADING, "Illustration A", 2),
        Element(ElementKind.PARAGRAPH, "See here.", 2),
        Element(ElementKind.HEADING, "Illustration B", 3),
        Element(ElementKind.PARAGRAPH, "See there.", 3),
    ]

    assert chunk_elements(elements, count_words, min_tokens=5) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=3,
            content=(
                "Setup\n\nPlace the board now.\n\n"
                "Illustration A\n\nSee here.\n\n"
                "Illustration B\n\nSee there."
            ),
        ),
    ]
