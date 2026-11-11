from pathlib import Path

import pymupdf

from app.ingestion.elements import Element, ElementKind
from app.ingestion.layout_parser import parse_pdf
from tests.helpers import add_text_page

BODY = (
    "Players take turns in clockwise order. On your turn, roll both "
    "dice and collect resources from every hex that shows the number rolled."
)

SETUP = "Shuffle the development cards and place them face down next to the board."

SCORING = "The first player to reach ten victory points wins the game immediately."


def save(doc: pymupdf.Document, tmp_path: Path) -> Path:
    path = tmp_path / "rules.pdf"
    doc.save(path)  # type: ignore[no-untyped-call]
    return path


def test_parse_pdf_returns_elements_in_reading_order(tmp_path: Path) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]

    add_text_page(
        doc, "Setup", [BODY, SETUP], bullets=["Place the board.", "Give each player their pieces."]
    )

    assert parse_pdf(save(doc, tmp_path)) == [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, BODY, 1),
        Element(ElementKind.PARAGRAPH, SETUP, 1),
        Element(ElementKind.LIST_ITEM, "Place the board.", 1),
        Element(ElementKind.LIST_ITEM, "Give each player their pieces.", 1),
    ]


def test_parse_pdf_gives_each_element_its_page(tmp_path: Path) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", [BODY])
    add_text_page(doc, "Trading", [BODY])

    elements = parse_pdf(save(doc, tmp_path))

    assert [(element.text, element.page) for element in elements] == [
        ("Setup", 1),
        (BODY, 1),
        ("Trading", 2),
        (BODY, 2),
    ]


def test_parse_pdf_drops_page_headers_and_page_numbers(tmp_path: Path) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for number, heading in enumerate(["Setup", "Trading", "Building"], start=1):
        add_text_page(doc, heading, [BODY, BODY], header="Example Game Rules", page_number=number)

    elements = parse_pdf(save(doc, tmp_path))

    assert [element.text for element in elements] == [
        "Setup",
        BODY,
        BODY,
        "Trading",
        BODY,
        BODY,
        "Building",
        BODY,
        BODY,
    ]


def test_parse_pdf_returns_a_table_as_markdown(tmp_path: Path) -> None:
    rows = [
        ["Building", "Cost", "Points"],
        ["Road", "Brick, Lumber", "0"],
        ["Settlement", "Brick, Lumber, Wool, Grain", "1"],
        ["City", "Ore x3, Grain x2", "2"],
    ]

    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = add_text_page(doc, "Building Costs", ["Each building needs the resources shown below."])
    for row_index, row in enumerate(rows):
        top = 200 + row_index * 24
        left = 72
        for cell, width in zip(row, [120, 220, 80], strict=True):
            box = pymupdf.Rect(left, top, left + width, top + 24)  # type: ignore[no-untyped-call]
            page.draw_rect(box, color=(0, 0, 0), width=0.8)
            font = "hebo" if row_index == 0 else "helv"
            page.insert_textbox(box + (4, 5, -4, 0), cell, fontsize=10, fontname=font)
            left += width

    elements = parse_pdf(save(doc, tmp_path))

    tables = [element for element in elements if element.kind == ElementKind.TABLE]
    assert len(tables) == 1
    assert tables[0].text == (
        "| Building | Cost | Points |\n"
        "|---|---|---|\n"
        "| Road | Brick, Lumber | 0 |\n"
        "| Settlement | Brick, Lumber, Wool, Grain | 1 |\n"
        "| City | Ore x3, Grain x2 | 2 |"
    )


def test_parse_pdf_reads_an_image_only_page_with_ocr(tmp_path: Path) -> None:
    scan = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(scan, "Scoring", [SCORING])
    picture = scan[0].get_pixmap(dpi=200)
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", [BODY])
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=picture)  # type: ignore[no-untyped-call]

    elements = parse_pdf(save(doc, tmp_path))

    assert [element for element in elements if element.page == 2] == [
        Element(ElementKind.HEADING, "Scoring", 2),
        Element(ElementKind.PARAGRAPH, SCORING, 2),
    ]
