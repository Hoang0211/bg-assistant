from pathlib import Path

import pymupdf
import pytest

from app.ingestion.elements import Element, ElementKind
from app.ingestion.parse_process import ParseFailedError, parse_in_process
from tests.helpers import add_text_page


def test_parse_in_process_returns_the_parsed_elements(tmp_path: Path) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", ["Players take turns in clockwise order."])
    path = tmp_path / "rules.pdf"
    doc.save(path)  # type: ignore[no-untyped-call]

    elements = parse_in_process(path, attempts=1)

    assert elements == [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Players take turns in clockwise order.", 1),
    ]


def test_parse_in_process_retries_and_then_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(ParseFailedError):
        parse_in_process(tmp_path / "missing.pdf", attempts=2)

    assert [record.getMessage() for record in caplog.records] == [
        "parse attempt 1 of 2 exited with code 1",
        "parse attempt 2 of 2 exited with code 1",
    ]
