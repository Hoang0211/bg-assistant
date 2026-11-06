import pytest

from app.db.models import ChunkType
from app.ingestion.chunker import ChunkLimits, TextChunk, chunk_elements
from app.ingestion.layout_parser import Element, ElementKind


def count_words(text: str) -> int:
    return len(text.split())


def limits(
    min_tokens: int = 0, target_tokens: int = 1000, max_tokens: int = 1000, overlap_tokens: int = 0
) -> ChunkLimits:
    return ChunkLimits(min_tokens, target_tokens, max_tokens, overlap_tokens)


TABLE = "| Building | Cost |\n|---|---|\n| Road | Brick |"

HEADER = "| Building | Cost |\n|---|---|"


def test_chunk_elements_starts_a_new_chunk_at_each_heading() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.LIST_ITEM, "Trade with the bank.", 1),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
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

    assert chunk_elements(elements, count_words, limits()) == [
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

    assert chunk_elements(elements, count_words, limits()) == [
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

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\nTrade with the bank.",
        )
    ]


def test_chunk_elements_returns_nothing_for_no_elements() -> None:
    assert chunk_elements([], count_words, limits()) == []


def test_chunk_elements_merges_a_small_section_into_the_previous_one() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board now.", 1),
        Element(ElementKind.HEADING, "Illustration A", 2),
        Element(ElementKind.PARAGRAPH, "See here.", 2),
    ]

    assert chunk_elements(elements, count_words, limits(min_tokens=5)) == [
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

    assert chunk_elements(elements, count_words, limits(min_tokens=5)) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=2,
            content="Setup\n\nWelcome\n\nPlace the board on the table.",
        ),
    ]


def test_chunk_elements_keeps_a_section_at_the_minimum() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Place the board.", 1),
        Element(ElementKind.HEADING, "Trading", 2),
        Element(ElementKind.PARAGRAPH, "Trade with banks.", 2),
    ]

    assert chunk_elements(elements, count_words, limits(min_tokens=4)) == [
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

    assert chunk_elements(elements, count_words, limits(min_tokens=80)) == [
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

    assert chunk_elements(elements, count_words, limits(min_tokens=5)) == [
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


def test_chunk_elements_keeps_a_section_at_the_max_whole() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "a b c d e f g h i j k", 1),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=10, max_tokens=12)) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Setup\n\na b c d e f g h i j k",
        ),
    ]


def test_chunk_elements_splits_a_long_section_between_elements() -> None:
    elements = [
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.PARAGRAPH, "a b c d e f.", 1),
        Element(ElementKind.PARAGRAPH, "g h i j k l.", 2),
        Element(ElementKind.PARAGRAPH, "m n o p q r.", 3),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=10, max_tokens=12)) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\na b c d e f.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=2,
            content="Trading\n\ng h i j k l.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=3,
            page_end=3,
            content="Trading\n\nm n o p q r.",
        ),
    ]


def test_chunk_elements_repeats_a_short_last_element_in_the_next_chunk() -> None:
    elements = [
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.PARAGRAPH, "a b c d e f.", 1),
        Element(ElementKind.PARAGRAPH, "g h.", 2),
        Element(ElementKind.PARAGRAPH, "i j k l m n o.", 3),
    ]

    assert chunk_elements(
        elements, count_words, limits(target_tokens=10, max_tokens=12, overlap_tokens=2)
    ) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=2,
            content="Trading\n\na b c d e f.\n\ng h.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=3,
            content="Trading\n\ng h.\n\ni j k l m n o.",
        ),
    ]


def test_chunk_elements_does_not_repeat_a_last_element_over_the_overlap() -> None:
    elements = [
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.PARAGRAPH, "a b c d e f.", 1),
        Element(ElementKind.PARAGRAPH, "g h.", 2),
        Element(ElementKind.PARAGRAPH, "i j k l m n o.", 3),
    ]

    assert chunk_elements(
        elements, count_words, limits(target_tokens=10, max_tokens=12, overlap_tokens=1)
    ) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=2,
            content="Trading\n\na b c d e f.\n\ng h.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=3,
            page_end=3,
            content="Trading\n\ni j k l m n o.",
        ),
    ]


def test_chunk_elements_splits_a_long_paragraph_at_sentence_ends() -> None:
    elements = [
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.PARAGRAPH, "a b c d e. f g h i j. k l m n o. p q r s t.", 1),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=10, max_tokens=12)) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\na b c d e.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\nf g h i j.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\nk l m n o.",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\np q r s t.",
        ),
    ]


def test_chunk_elements_splits_a_long_sentence_between_words() -> None:
    elements = [
        Element(ElementKind.HEADING, "Trading", 1),
        Element(ElementKind.PARAGRAPH, "a b c d e f g h i j k l m n o p q r s t u v w x y", 1),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=10, max_tokens=12)) == [
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\na b c d e f g h i",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\nj k l m n o p q r",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="Trading\n\ns t u v w x y",
        ),
    ]


def test_chunk_elements_splits_a_long_section_with_no_heading() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "a b c d e f g.", 1),
        Element(ElementKind.PARAGRAPH, "h i j k l m n.", 2),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=10, max_tokens=12)) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=1,
            content="a b c d e f g.",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=2,
            content="h i j k l m n.",
        ),
    ]


def test_chunk_elements_joins_a_paragraph_cut_by_a_page_break() -> None:
    elements = [
        Element(ElementKind.HEADING, "Robber", 4),
        Element(ElementKind.PARAGRAPH, "When a 7 is rolled, players with more than", 4),
        Element(ElementKind.PARAGRAPH, "7 cards discard half.", 5),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Robber",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content="Robber\n\nWhen a 7 is rolled, players with more than 7 cards discard half.",
        ),
    ]


@pytest.mark.parametrize("ending", [".", "!", "?", ":"])
def test_chunk_elements_does_not_join_text_that_ends_a_sentence(ending: str) -> None:
    elements = [
        Element(ElementKind.HEADING, "Robber", 4),
        Element(ElementKind.PARAGRAPH, f"Move the robber{ending}", 4),
        Element(ElementKind.PARAGRAPH, "Steal one card.", 5),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Robber",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content=f"Robber\n\nMove the robber{ending}\n\nSteal one card.",
        ),
    ]


def test_chunk_elements_does_not_join_text_on_the_same_page() -> None:
    elements = [
        Element(ElementKind.HEADING, "Robber", 4),
        Element(ElementKind.PARAGRAPH, "Move the robber", 4),
        Element(ElementKind.PARAGRAPH, "Steal one card.", 4),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Robber",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=4,
            content="Robber\n\nMove the robber\n\nSteal one card.",
        ),
    ]


def test_chunk_elements_does_not_join_text_across_a_skipped_page() -> None:
    elements = [
        Element(ElementKind.HEADING, "Robber", 4),
        Element(ElementKind.PARAGRAPH, "Move the robber", 4),
        Element(ElementKind.PARAGRAPH, "Steal one card.", 6),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Robber",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=6,
            content="Robber\n\nMove the robber\n\nSteal one card.",
        ),
    ]


@pytest.mark.parametrize("kind", [ElementKind.HEADING, ElementKind.CAPTION])
def test_chunk_elements_does_not_join_text_after_a_non_text_element(kind: ElementKind) -> None:
    elements = [
        Element(kind, "Illustration", 4),
        Element(ElementKind.PARAGRAPH, "Steal one card.", 5),
    ]
    chunks = chunk_elements(elements, count_words, limits())

    assert [chunk.content for chunk in chunks] == ["Illustration\n\nSteal one card."]


@pytest.mark.parametrize("kind", [ElementKind.CAPTION, ElementKind.LIST_ITEM])
def test_chunk_elements_does_not_join_a_non_paragraph_on_the_next_page(kind: ElementKind) -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Move the robber", 4),
        Element(kind, "Steal one card.", 5),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content="Move the robber\n\nSteal one card.",
        ),
    ]


def test_chunk_elements_does_not_join_a_heading_on_the_next_page() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Move the robber", 4),
        Element(ElementKind.HEADING, "Trading", 5),
        Element(ElementKind.PARAGRAPH, "Trade with the bank.", 5),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=4,
            content="Move the robber",
        ),
        TextChunk(
            section_path="Trading",
            chunk_type=ChunkType.SECTION,
            page_start=5,
            page_end=5,
            content="Trading\n\nTrade with the bank.",
        ),
    ]


def test_chunk_elements_joins_a_list_item_cut_by_a_page_break() -> None:
    elements = [
        Element(ElementKind.LIST_ITEM, "Discard half your cards if you hold more than", 4),
        Element(ElementKind.PARAGRAPH, "7 cards.", 5),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content="Discard half your cards if you hold more than 7 cards.",
        )
    ]


def test_chunk_elements_joins_a_paragraph_over_three_pages() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Discard half your cards", 4),
        Element(ElementKind.PARAGRAPH, "if you hold more than", 5),
        Element(ElementKind.PARAGRAPH, "7 cards.", 6),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=6,
            content="Discard half your cards if you hold more than 7 cards.",
        )
    ]


def test_chunk_elements_keeps_the_page_range_when_splitting_a_joined_paragraph() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Discard half your cards", 4),
        Element(ElementKind.PARAGRAPH, "if you hold more than 7 cards. Then move the robber.", 5),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=11, max_tokens=11)) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content="Discard half your cards if you hold more than 7 cards.",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content="Then move the robber.",
        ),
    ]


def test_chunk_elements_does_not_join_text_that_starts_with_a_capital() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Grimm Edition", 1),
        Element(ElementKind.PARAGRAPH, "Snow White and many other tales.", 2),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=1,
            page_end=2,
            content="Grimm Edition\n\nSnow White and many other tales.",
        ),
    ]


def test_chunk_elements_puts_a_table_in_its_own_chunk() -> None:
    elements = [
        Element(ElementKind.HEADING, "Costs", 3),
        Element(ElementKind.PARAGRAPH, "Pay first.", 3),
        Element(ElementKind.TABLE, TABLE, 3),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.SECTION,
            page_start=3,
            page_end=3,
            content="Costs\n\nPay first.",
        ),
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{TABLE}",
        ),
    ]


def test_chunk_elements_keeps_only_the_table_chunk_for_a_heading_with_no_text() -> None:
    elements = [
        Element(ElementKind.HEADING, "Costs", 3),
        Element(ElementKind.TABLE, TABLE, 3),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{TABLE}",
        ),
    ]


def test_chunk_elements_keeps_a_table_with_no_heading() -> None:
    elements = [
        Element(ElementKind.TABLE, TABLE, 3),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=TABLE,
        ),
    ]


def test_chunk_elements_keeps_the_text_around_a_table_in_one_chunk() -> None:
    elements = [
        Element(ElementKind.HEADING, "Costs", 3),
        Element(ElementKind.PARAGRAPH, "Pay first.", 3),
        Element(ElementKind.TABLE, TABLE, 3),
        Element(ElementKind.PARAGRAPH, "Then build.", 3),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.SECTION,
            page_start=3,
            page_end=3,
            content="Costs\n\nPay first.\n\nThen build.",
        ),
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{TABLE}",
        ),
    ]


def test_chunk_elements_does_not_merge_a_small_table() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 2),
        Element(ElementKind.PARAGRAPH, "Place the board.", 2),
        Element(ElementKind.HEADING, "Costs", 3),
        Element(ElementKind.TABLE, TABLE, 3),
    ]

    assert chunk_elements(elements, count_words, limits(min_tokens=20)) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=2,
            content="Setup\n\nPlace the board.",
        ),
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{TABLE}",
        ),
    ]


def test_chunk_elements_does_not_join_text_on_either_side_of_a_table() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Pay with", 4),
        Element(ElementKind.TABLE, TABLE, 4),
        Element(ElementKind.PARAGRAPH, "two bricks.", 5),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.SECTION,
            page_start=4,
            page_end=5,
            content="Pay with\n\ntwo bricks.",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.TABLE,
            page_start=4,
            page_end=4,
            content=TABLE,
        ),
    ]


def test_chunk_elements_keeps_a_table_at_the_max_whole() -> None:
    elements = [
        Element(ElementKind.HEADING, "Costs", 3),
        Element(ElementKind.TABLE, TABLE, 3),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=12, max_tokens=12)) == [
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{TABLE}",
        ),
    ]


def test_chunk_elements_splits_a_long_table_between_rows() -> None:
    elements = [
        Element(ElementKind.HEADING, "Costs", 3),
        Element(
            ElementKind.TABLE,
            f"{HEADER}\n| Road | Brick |\n| City | Ore |\n| Farm | Wool |\n| Port | Clay |",
            3,
        ),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=17, max_tokens=17)) == [
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{HEADER}\n| Road | Brick |\n| City | Ore |",
        ),
        TextChunk(
            section_path="Costs",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"Costs\n\n{HEADER}\n| Farm | Wool |\n| Port | Clay |",
        ),
    ]


def test_chunk_elements_splits_a_long_table_row_between_words() -> None:
    elements = [
        Element(ElementKind.TABLE, f"{HEADER}\n| one two three four five six |", 3),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=10, max_tokens=10)) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"{HEADER}\n| one two three",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.TABLE,
            page_start=3,
            page_end=3,
            content=f"{HEADER}\nfour five six |",
        ),
    ]


def test_chunk_elements_puts_each_glossary_entry_in_its_own_chunk() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nWife: Share a space.",
        ),
    ]


def test_chunk_elements_keeps_a_short_run_of_entries_in_its_section() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.SECTION,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.\n\nQueen: Play a card.\n\nRanger: Move a worker.",
        )
    ]


def test_chunk_elements_keeps_glossary_entries_with_no_heading() -> None:
    elements = [
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Bard: Gain a point.",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Queen: Play a card.",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Ranger: Move a worker.",
        ),
        TextChunk(
            section_path="",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Wife: Share a space.",
        ),
    ]


def test_chunk_elements_does_not_count_entries_split_by_other_text() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Shuffle the deck.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.SECTION,
            page_start=18,
            page_end=18,
            content=(
                "Cards\n\nBard: Gain a point.\n\nQueen: Play a card.\n\nShuffle the deck."
                "\n\nRanger: Move a worker.\n\nWife: Share a space."
            ),
        )
    ]


def test_chunk_elements_treats_list_items_as_glossary_entries() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.LIST_ITEM, "Bard: Gain a point.", 18),
        Element(ElementKind.LIST_ITEM, "Queen: Play a card.", 18),
        Element(ElementKind.LIST_ITEM, "Ranger: Move a worker.", 18),
        Element(ElementKind.LIST_ITEM, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nWife: Share a space.",
        ),
    ]


def test_chunk_elements_does_not_merge_small_glossary_entries() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits(min_tokens=50)) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nWife: Share a space.",
        ),
    ]


def test_chunk_elements_splits_a_long_glossary_entry() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point. Draw a card.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits(target_tokens=7, max_tokens=7)) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nDraw a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nWife: Share a space.",
        ),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Move first. Then: pay.",
        "the bard: Gain a point.",
        "A very long opening to a sentence that keeps going on: pay.",
        "Bard:",
    ],
)
def test_chunk_elements_does_not_treat_other_text_as_a_glossary_entry(text: str) -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(
            ElementKind.PARAGRAPH,
            text,
            18,
        ),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.SECTION,
            page_start=18,
            page_end=18,
            content=(
                f"Cards\n\n{text}\n\nQueen: Play a card."
                "\n\nRanger: Move a worker.\n\nWife: Share a space."
            ),
        )
    ]


def test_chunk_elements_keeps_the_pages_of_each_glossary_entry() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point and", 18),
        Element(ElementKind.PARAGRAPH, "draw a card.", 19),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 19),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 19),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 19),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=19,
            content="Cards\n\nBard: Gain a point and draw a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=19,
            page_end=19,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=19,
            page_end=19,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=19,
            page_end=19,
            content="Cards\n\nWife: Share a space.",
        ),
    ]


def test_chunk_elements_keeps_text_before_a_glossary_in_its_section() -> None:
    elements = [
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "These cards score at game end.", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.SECTION,
            page_start=18,
            page_end=18,
            content="Cards\n\nThese cards score at game end.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nWife: Share a space.",
        ),
    ]


def test_chunk_elements_uses_the_nearest_heading_for_glossary_entries() -> None:
    elements = [
        Element(ElementKind.HEADING, "Setup", 17),
        Element(ElementKind.PARAGRAPH, "Place the board.", 17),
        Element(ElementKind.HEADING, "Cards", 18),
        Element(ElementKind.PARAGRAPH, "Bard: Gain a point.", 18),
        Element(ElementKind.PARAGRAPH, "Queen: Play a card.", 18),
        Element(ElementKind.PARAGRAPH, "Ranger: Move a worker.", 18),
        Element(ElementKind.PARAGRAPH, "Wife: Share a space.", 18),
        Element(ElementKind.HEADING, "Scoring", 19),
        Element(ElementKind.PARAGRAPH, "Count your points.", 19),
    ]

    assert chunk_elements(elements, count_words, limits()) == [
        TextChunk(
            section_path="Setup",
            chunk_type=ChunkType.SECTION,
            page_start=17,
            page_end=17,
            content="Setup\n\nPlace the board.",
        ),
        TextChunk(
            section_path="Scoring",
            chunk_type=ChunkType.SECTION,
            page_start=19,
            page_end=19,
            content="Scoring\n\nCount your points.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nBard: Gain a point.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nQueen: Play a card.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nRanger: Move a worker.",
        ),
        TextChunk(
            section_path="Cards",
            chunk_type=ChunkType.GLOSSARY,
            page_start=18,
            page_end=18,
            content="Cards\n\nWife: Share a space.",
        ),
    ]
