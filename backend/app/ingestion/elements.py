"""The parsed-page types shared by the ingestion modules; this module imports nothing heavy."""

from dataclasses import dataclass
from enum import StrEnum


class ElementKind(StrEnum):
    """What kind of content an element holds."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CAPTION = "caption"


@dataclass(frozen=True)
class Element:
    """One piece of a parsed page, in reading order."""

    kind: ElementKind
    text: str
    page: int
    last_page: int | None = None  # set when the text carries on over a page break
