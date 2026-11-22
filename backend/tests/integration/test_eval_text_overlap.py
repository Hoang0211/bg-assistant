from collections import Counter
from datetime import datetime
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook
from app.evaluation.text_overlap import (
    PageOverlap,
    RulebookOverlap,
    compare_page,
    compare_rulebook,
    format_text_report,
    rulebook_overlaps,
)
from tests.helpers import add_text_page

RULE = "Players take turns in clockwise order."


def _page(page: int, pdf_words: int, missing: int, added: int) -> PageOverlap:
    return PageOverlap(page, pdf_words, Counter({"gone": missing}), Counter({"new": added}))


def test_compare_page_counts_the_missing_and_added_words() -> None:
    overlap = compare_page(3, "Roll two dice and move.", "# Roll\n\nRoll **three** dice.")

    assert overlap == PageOverlap(
        page=3,
        pdf_words=5,
        missing=Counter({"two": 1, "and": 1, "move": 1}),
        added=Counter({"roll": 1, "three": 1}),
    )
    assert overlap.kept == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("pdf_text", "markdown"),
    [
        ("SETUP\nPlace the board.", "## Setup\n\n> - Place *the* **board**."),
        ("the player’s turn", "the player's turn"),
        ("every-\nbody wins", "everybody wins"),
    ],
    ids=["case and symbols", "curly apostrophe", "hyphen at a line break"],
)
def test_compare_page_finds_no_difference_in_formatting(pdf_text: str, markdown: str) -> None:
    overlap = compare_page(1, pdf_text, markdown)

    assert (overlap.missing, overlap.added) == (Counter(), Counter())


def test_compare_rulebook_checks_only_pages_with_enough_text() -> None:
    markdown = "<!-- page 1 -->\n\nRoll the dice.\n\n<!-- page 2 -->\n\n<!-- page 3 -->\n\nTrade.\n"

    overlaps = compare_rulebook(["Roll the dice.", "x", "Trade cards."], markdown, min_chars=5)

    assert [(overlap.page, overlap.kept) for overlap in overlaps] == [(1, 1.0), (3, 0.5)]


def test_compare_rulebook_skips_a_page_with_no_words() -> None:
    symbols = "★ ✦ → ← ☆ " * 3  # over the minimum, but nothing a word could match

    overlaps = compare_rulebook([symbols, "Trade cards."], "<!-- page 2 -->\n\nTrade.\n", 5)

    assert [overlap.page for overlap in overlaps] == [2]


def test_compare_rulebook_counts_a_page_missing_from_the_markdown_as_all_missing() -> None:
    overlaps = compare_rulebook(["Roll the dice."], "<!-- page 2 -->\n\nTrade.\n", min_chars=5)

    assert [(overlap.page, overlap.kept) for overlap in overlaps] == [(1, 0.0)]


async def test_rulebook_overlaps_compares_each_rulebooks_markdown_with_its_pdf(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", [RULE])
    doc.save(tmp_path / "rules.pdf")  # type: ignore[no-untyped-call]
    game = Game(name="Base")
    db_session.add(game)
    await db_session.flush()
    for filename, markdown in [
        ("parsed.pdf", f"<!-- page 1 -->\n\n# Setup\n\n{RULE}\n"),
        ("new.pdf", None),
    ]:
        db_session.add(
            Rulebook(
                game_id=game.id,
                filename=filename,
                storage_path="rules.pdf",
                page_count=1,
                sha256=filename.ljust(64, "0"),
                markdown=markdown,
            )
        )
    await db_session.flush()

    overlaps = await rulebook_overlaps(db_session, tmp_path, min_chars=10)

    assert [
        (overlap.filename, overlap.page_count, [page.kept for page in overlap.pages])
        for overlap in overlaps
    ] == [("parsed.pdf", 1, [1.0]), ("new.pdf", 1, [0.0])]


def test_format_text_report_shows_each_rulebook_then_each_page_least_kept_first() -> None:
    rulebooks = [
        RulebookOverlap("a.pdf", 3, [_page(1, 100, 50, 0), _page(2, 100, 0, 3)]),
        RulebookOverlap("b.pdf", 2, [_page(4, 200, 50, 1)]),
        RulebookOverlap("scanned.pdf", 5, []),
    ]

    report = format_text_report(rulebooks, 100, datetime(2026, 11, 21, 13, 14))

    assert report == (
        "# Text kept by the LLM parser: 2026-11-21 13:14\n"
        "\n"
        "- Each page's Markdown is compared with the PDF's text layer as lower-case words;"
        " Markdown symbols and page markers aren't words.\n"
        "- Kept: the share of the text layer's words the Markdown has, so a low share means"
        " dropped text. Added: the Markdown's words the text layer doesn't have: changed or"
        " invented text, or text read from a picture that has no text layer.\n"
        "- A page with under 100 characters in its text layer (scanned or nearly blank), or"
        " with no words in it, has nothing to compare with and isn't checked.\n"
        "\n"
        "| Rulebook | Pages checked | Kept | Added words |\n"
        "| --- | --: | --: | --: |\n"
        "| a.pdf | 2 of 3 | 75% | 3 |\n"
        "| b.pdf | 1 of 2 | 75% | 1 |\n"
        "| scanned.pdf | 0 of 5 | – | – |\n"
        "\n"
        "## Pages, least kept first\n"
        "\n"
        "| Rulebook | Page | Text-layer words | Kept | Added words |\n"
        "| --- | --: | --: | --: | --: |\n"
        "| a.pdf | 1 | 100 | 50% | 0 |\n"
        "| b.pdf | 4 | 200 | 75% | 1 |\n"
        "| a.pdf | 2 | 100 | 100% | 3 |\n"
    )
