import re
from functools import cache
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.node import DocItem
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import TextItem
from docling_core.types.doc.labels import DocItemLabel

from app.config import get_settings
from app.ingestion.elements import Element, ElementKind
from app.ingestion.pdf_info import low_text_pages

# Labels not listed here (pictures, charts, formulas, code, the table of contents) are skipped.
_KINDS: dict[DocItemLabel, ElementKind] = {
    DocItemLabel.TITLE: ElementKind.HEADING,
    DocItemLabel.SECTION_HEADER: ElementKind.HEADING,
    DocItemLabel.TEXT: ElementKind.PARAGRAPH,
    DocItemLabel.PARAGRAPH: ElementKind.PARAGRAPH,
    DocItemLabel.FOOTNOTE: ElementKind.PARAGRAPH,
    DocItemLabel.LIST_ITEM: ElementKind.LIST_ITEM,
    DocItemLabel.TABLE: ElementKind.TABLE,
    DocItemLabel.CAPTION: ElementKind.CAPTION,
}


@cache  # one converter per setting: creating one loads the layout models
def _converter(ocr: bool) -> DocumentConverter:
    options = PdfPipelineOptions(do_ocr=ocr)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def _compact_table(markdown: str) -> str:
    return re.sub(r"-{3,}", "---", re.sub(r" {2,}", " ", markdown))


def _to_elements(document: DoclingDocument) -> list[Element]:
    elements: list[Element] = []
    for item, _level in document.iterate_items():
        if not isinstance(item, DocItem) or not item.prov:
            continue

        kind = _KINDS.get(item.label)
        if kind is None:
            continue

        if isinstance(item, TableItem):
            text = _compact_table(item.export_to_markdown(doc=document))
        elif isinstance(item, TextItem):
            text = item.text.strip()
        else:
            continue

        if not text:
            continue

        elements.append(Element(kind=kind, text=text, page=item.prov[0].page_no))

    return elements


def parse_pdf(path: Path) -> list[Element]:
    """Parse a PDF into elements in reading order.

    Pages with little text are parsed again with OCR.
    """
    elements = _to_elements(_converter(ocr=False).convert(path).document)

    for page in low_text_pages(path, get_settings().ocr_min_page_chars):
        ocr_document = _converter(ocr=True).convert(path, page_range=(page, page)).document
        kept = [element for element in elements if element.page != page]
        elements = kept + _to_elements(ocr_document)

    return sorted(elements, key=lambda element: element.page)
