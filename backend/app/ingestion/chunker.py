import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import groupby

from app.db.models import ChunkType
from app.ingestion.elements import Element, ElementKind


@dataclass(frozen=True)
class TextChunk:
    """One section of a rulebook, ready to embed and store as a `Chunk` row."""

    section_path: str
    chunk_type: ChunkType
    page_start: int
    page_end: int
    content: str


@dataclass(frozen=True)
class ChunkLimits:
    """Chunk sizes, in tokens."""

    min_tokens: int
    target_tokens: int
    max_tokens: int
    overlap_tokens: int


# A section's path and its elements. Its own heading, if it has one, comes first.
_Section = tuple[str, list[Element]]

# A glossary entry looks like "Term: definition", and it takes a run of them to count as a glossary.
_GLOSSARY_ENTRY = re.compile(r"[A-Z][^.:!?]{0,40}: \S")
_MIN_GLOSSARY_ENTRIES = 4

# Headings of sections about who made the game, not how to play it.
_CREDITS_HEADING = re.compile(
    r"credits|.*acknowledge?ments?|playtesters|.*\binc\.?|www\..*", re.IGNORECASE
)


def _content(section: list[Element]) -> str:
    return "\n\n".join(element.text for element in section)


def _last_page(element: Element) -> int:
    return element.last_page or element.page


def _continues(previous: Element, element: Element) -> bool:
    return (
        previous.kind in (ElementKind.PARAGRAPH, ElementKind.LIST_ITEM)
        and element.kind == ElementKind.PARAGRAPH
        and element.page == _last_page(previous) + 1
        and not previous.text.endswith((".", "!", "?", ":"))
        and not element.text[0].isupper()
    )


def _join_page_breaks(elements: list[Element]) -> list[Element]:
    joined: list[Element] = []
    for element in elements:
        if joined and _continues(joined[-1], element):
            previous = joined[-1]
            joined[-1] = replace(
                previous, text=f"{previous.text} {element.text}", last_page=element.page
            )
        else:
            joined.append(element)
    return joined


def _split_at_words(text: str, count_tokens: Callable[[str], int], limit: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split():
        if current and count_tokens(" ".join([*current, word])) > limit:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    pieces.append(" ".join(current))
    return pieces


def _split_long_element(
    element: Element, count_tokens: Callable[[str], int], limit: int
) -> list[Element]:
    if count_tokens(element.text) <= limit:
        return [element]

    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", element.text):
        if count_tokens(sentence) <= limit:
            pieces.append(sentence)
        else:
            pieces.extend(_split_at_words(sentence, count_tokens, limit))

    return [replace(element, text=piece) for piece in pieces]


def _split_long_section(
    heading: str,
    section: list[Element],
    count_tokens: Callable[[str], int],
    limits: ChunkLimits,
) -> list[_Section]:
    if count_tokens(_content(section)) <= limits.max_tokens:
        return [(heading, section)]

    limit = limits.target_tokens - count_tokens(heading)
    pieces = [
        piece for element in section for piece in _split_long_element(element, count_tokens, limit)
    ]

    parts: list[_Section] = []
    current: list[Element] = []
    for piece in pieces:
        if current and count_tokens(_content([*current, piece])) > limits.target_tokens:
            parts.append((heading, current))
            last = current[-1]
            overlap = [last] if count_tokens(last.text) <= limits.overlap_tokens else []
            repeated = [Element(ElementKind.HEADING, heading, piece.page)] if heading else []
            current = [*repeated, *overlap]
        current.append(piece)
    parts.append((heading, current))
    return parts


def _drop_credits(elements: list[Element]) -> list[Element]:
    kept: list[Element] = []
    dropping = False
    for element in elements:
        if element.kind == ElementKind.HEADING:
            dropping = bool(_CREDITS_HEADING.fullmatch(element.text))
        if not dropping:
            kept.append(element)
    return kept


def _pull_out_tables(elements: list[Element]) -> tuple[list[Element], list[tuple[str, Element]]]:
    text: list[Element] = []
    tables: list[tuple[str, Element]] = []
    heading = ""
    for element in elements:
        if element.kind == ElementKind.HEADING:
            heading = element.text
        if element.kind == ElementKind.TABLE:
            tables.append((heading, element))
        else:
            text.append(element)
    return text, tables


def _split_long_table(
    heading: str, table: str, count_tokens: Callable[[str], int], limits: ChunkLimits
) -> list[str]:
    whole = f"{heading}\n\n{table}" if heading else table
    if count_tokens(whole) <= limits.max_tokens:
        return [whole]

    lines = table.split("\n")
    header = "\n".join(lines[:2])
    top = f"{heading}\n\n{header}" if heading else header
    limit = limits.target_tokens - count_tokens(top)
    rows = [piece for row in lines[2:] for piece in _split_at_words(row, count_tokens, limit)]

    pieces: list[str] = []
    current: list[str] = []
    for row in rows:
        if current and count_tokens("\n".join([top, *current, row])) > limits.target_tokens:
            pieces.append("\n".join([top, *current]))
            current = []
        current.append(row)
    pieces.append("\n".join([top, *current]))
    return pieces


def _is_glossary_entry(element: Element) -> bool:
    return element.kind in (ElementKind.PARAGRAPH, ElementKind.LIST_ITEM) and bool(
        _GLOSSARY_ENTRY.match(element.text)
    )


def _pull_out_glossary(elements: list[Element]) -> tuple[list[Element], list[tuple[str, Element]]]:
    text: list[Element] = []
    entries: list[tuple[str, Element]] = []
    heading = ""
    for is_entry, group in groupby(elements, key=_is_glossary_entry):
        run = list(group)
        if is_entry and len(run) >= _MIN_GLOSSARY_ENTRIES:
            entries.extend((heading, element) for element in run)
            continue

        text.extend(run)
        for element in run:
            if element.kind == ElementKind.HEADING:
                heading = element.text
    return text, entries


def _to_chunk(heading: str, section: list[Element], chunk_type: ChunkType) -> TextChunk:
    return TextChunk(
        section_path=heading,
        chunk_type=chunk_type,
        page_start=min(element.page for element in section),
        page_end=max(_last_page(element) for element in section),
        content=_content(section),
    )


def _split_at_headings(elements: list[Element]) -> list[_Section]:
    sections: list[_Section] = [("", [])]
    for element in elements:
        if element.kind == ElementKind.HEADING:
            sections.append((element.text, [element]))
        else:
            sections[-1][1].append(element)

    return [
        (heading, section)
        for heading, section in sections
        if any(element.kind != ElementKind.HEADING for element in section)
    ]


def _merge_small_sections(
    sections: list[_Section], count_tokens: Callable[[str], int], min_tokens: int
) -> list[_Section]:
    merged: list[_Section] = []
    for heading, section in sections:
        if merged and count_tokens(_content(section)) < min_tokens:
            merged[-1][1].extend(section)
        else:
            merged.append((heading, section))

    if len(merged) > 1 and count_tokens(_content(merged[0][1])) < min_tokens:
        (_, first), (heading, second) = merged[:2]
        merged[:2] = [(heading, [second[0], *first, *second[1:]])]

    return merged


def chunk_elements(
    elements: list[Element], count_tokens: Callable[[str], int], limits: ChunkLimits
) -> list[TextChunk]:
    """Split parsed elements at headings, then merge small sections and split long ones."""
    text, tables = _pull_out_tables(_drop_credits(_join_page_breaks(elements)))
    text, entries = _pull_out_glossary(text)
    merged = _merge_small_sections(_split_at_headings(text), count_tokens, limits.min_tokens)
    sections = [
        part
        for heading, section in merged
        for part in _split_long_section(heading, section, count_tokens, limits)
    ]
    chunks = [_to_chunk(heading, section, ChunkType.SECTION) for heading, section in sections]

    for heading, table in tables:
        for content in _split_long_table(heading, table.text, count_tokens, limits):
            chunks.append(
                TextChunk(
                    section_path=heading,
                    chunk_type=ChunkType.TABLE,
                    page_start=table.page,
                    page_end=table.page,
                    content=content,
                )
            )

    for heading, entry in entries:
        section = [Element(ElementKind.HEADING, heading, entry.page), entry] if heading else [entry]
        for _, part in _split_long_section(heading, section, count_tokens, limits):
            chunks.append(_to_chunk(heading, part, ChunkType.GLOSSARY))

    return chunks
