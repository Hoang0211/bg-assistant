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


def chunk_elements(elements: list[Element]) -> list[TextChunk]:
    """Split parsed elements into chunks, one per section."""
    sections: list[tuple[str, list[Element]]] = [("", [])]
    for element in elements:
        if element.kind == ElementKind.HEADING:
            sections.append((element.text, [element]))
        else:
            sections[-1][1].append(element)

    chunks: list[TextChunk] = []
    for heading, section in sections:
        body = [element.text for element in section if element.kind != ElementKind.HEADING]
        if not body:
            continue
        parts = [heading, *body] if heading else body
        chunks.append(
            TextChunk(
                section_path=heading,
                chunk_type=ChunkType.SECTION,
                page_start=section[0].page,
                page_end=section[-1].page,
                content="\n\n".join(parts),
            )
        )

    return chunks
