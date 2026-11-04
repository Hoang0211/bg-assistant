import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from app.db.models import ChunkType
from app.ingestion.layout_parser import Element, ElementKind


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


def _content(section: list[Element]) -> str:
    return "\n\n".join(element.text for element in section)


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
    merged = _merge_small_sections(_split_at_headings(elements), count_tokens, limits.min_tokens)
    sections = [
        part
        for heading, section in merged
        for part in _split_long_section(heading, section, count_tokens, limits)
    ]
    chunks: list[TextChunk] = []
    for heading, section in sections:
        chunks.append(
            TextChunk(
                section_path=heading,
                chunk_type=ChunkType.SECTION,
                page_start=min(element.page for element in section),
                page_end=max(element.page for element in section),
                content=_content(section),
            )
        )

    return chunks
