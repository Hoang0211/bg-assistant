from collections.abc import Callable
from dataclasses import dataclass

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


# A section's path and its elements. Its own heading, if it has one, comes first.
_Section = tuple[str, list[Element]]


def _content(section: list[Element]) -> str:
    return "\n\n".join(element.text for element in section)


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
    elements: list[Element], count_tokens: Callable[[str], int], min_tokens: int
) -> list[TextChunk]:
    """Split parsed elements into chunks at headings, merging small sections."""
    sections = _merge_small_sections(_split_at_headings(elements), count_tokens, min_tokens)

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
