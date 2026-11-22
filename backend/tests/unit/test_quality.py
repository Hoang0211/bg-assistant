from app.ingestion.elements import Element, ElementKind
from app.ingestion.quality import ParseReport, build_report


def test_build_report_lists_pages_with_no_text() -> None:
    report = build_report(
        [
            Element(ElementKind.PARAGRAPH, "Roll the dice.", 1),
            Element(ElementKind.PARAGRAPH, "Trade with the bank.", 3),
        ],
        chunk_count=2,
        page_count=4,
    )

    assert report == ParseReport(chunk_count=2, empty_pages=[2, 4])


def test_build_report_counts_the_page_a_joined_sentence_ends_on_as_text() -> None:
    report = build_report(
        [
            Element(
                ElementKind.PARAGRAPH,
                "When a 7 is rolled, players with more than 7 cards discard half.",
                6,
                last_page=7,
            ),
        ],
        chunk_count=1,
        page_count=8,
    )

    assert report.empty_pages == [1, 2, 3, 4, 5, 8]


def test_build_report_counts_any_element_as_text() -> None:
    report = build_report(
        [
            Element(ElementKind.HEADING, "Setup", 1),
            Element(ElementKind.CAPTION, "Hills produce brick", 2),
            Element(ElementKind.TABLE, "| Building | Cost |\n|---|---|\n| Road | Brick |", 3),
        ],
        chunk_count=2,
        page_count=3,
    )

    assert report == ParseReport(chunk_count=2, empty_pages=[])
