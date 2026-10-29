import pymupdf


def make_pdf(pages: int, **save_options: object) -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for _ in range(pages):
        doc.new_page()
    data: bytes = doc.tobytes(**save_options)  # type: ignore[no-untyped-call]
    return data
