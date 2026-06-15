import fitz

def render_pages(pid_path: str, dpi: int = 375) -> list[bytes]:
    doc = fitz.open(pid_path)
    images = []
    for page in doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    return images
