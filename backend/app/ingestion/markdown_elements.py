"""Read the LLM parser's Markdown into the elements the chunker takes."""

import re

from app.ingestion.chunker import join_page_breaks
from app.ingestion.elements import PATH_SEPARATOR, Element, ElementKind

_PAGE_MARKER = re.compile(r"<!-- page (\d+) -->")
_HEADING = re.compile(r"(#{1,6}) +(.+)")
_LIST_ITEM = re.compile(r"(?:[-*+]|\d+[.)]) ")


def _blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if line.strip() and not _HEADING.fullmatch(line) and not _PAGE_MARKER.fullmatch(line):
            current.append(line.rstrip())
            continue

        if current:
            blocks.append("\n".join(current))
            current = []
        if line.strip():
            blocks.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _list_items(block: str) -> list[str]:
    items: list[str] = []
    for line in block.split("\n"):
        if _LIST_ITEM.match(line) or not items:
            items.append(line)
        else:
            items[-1] += f"\n{line}"  # a nested item or a continued line stays with its item
    return items


def _read_blocks(markdown: str) -> list[Element]:
    elements: list[Element] = []
    path: list[tuple[int, str]] = []  # the open headings, with their levels
    page = 1
    for block in _blocks(markdown):
        if marker := _PAGE_MARKER.fullmatch(block):
            page = int(marker[1])
        elif heading := _HEADING.fullmatch(block):
            level = len(heading[1])
            path = [*(parent for parent in path if parent[0] < level), (level, heading[2].strip())]
            text = PATH_SEPARATOR.join(title for _, title in path)
            elements.append(Element(ElementKind.HEADING, text, page))
        elif all(line.startswith("|") for line in block.split("\n")):
            elements.append(Element(ElementKind.TABLE, block, page))
        elif _LIST_ITEM.match(block):
            elements.extend(
                Element(ElementKind.LIST_ITEM, item, page) for item in _list_items(block)
            )
        else:
            elements.append(Element(ElementKind.PARAGRAPH, block, page))
    return elements


def _continue_sections(elements: list[Element]) -> list[Element]:
    continued: list[Element] = []
    path = ""
    for element in elements:
        if element.kind == ElementKind.HEADING:
            path = element.text
        elif path and continued and element.page > continued[-1].page:
            continued.append(Element(ElementKind.HEADING, path, element.page))
        continued.append(element)
    return continued


def markdown_to_elements(markdown: str) -> list[Element]:
    """Read Markdown with `<!-- page N -->` lines into elements, in order.

    A heading's text is its section path, built from the heading levels. A page that doesn't
    start with a heading continues the previous page's section, under a repeat of its path, so
    no chunk spans a page break; only a sentence cut by the break is joined across it.
    """
    return _continue_sections(join_page_breaks(_read_blocks(markdown)))
