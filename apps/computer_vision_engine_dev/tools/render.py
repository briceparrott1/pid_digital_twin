import fitz


def render_page(pdf_path: str, page_index: int = 0, dpi: int = 375) -> bytes:
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")
