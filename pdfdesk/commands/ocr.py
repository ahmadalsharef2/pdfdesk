"""OCR (plan phase 2) via OCRmyPDF + Tesseract."""
from __future__ import annotations

import pymupdf

from .registry import command


def is_scanned(doc: pymupdf.Document, page: int = 0) -> bool:
    p = doc[page]
    if p.get_text().strip():
        return False
    imgs = p.get_image_info()
    return any(pymupdf.Rect(i["bbox"]).get_area() >= 0.9 * p.rect.get_area() for i in imgs)


@command("Ocr.Run")
def ocr(src: str, dst: str, languages=("eng",), deskew: bool = True, rotate: bool = True,
        pages: str | None = None, optimize: int = 1):
    import ocrmypdf
    ocrmypdf.ocr(src, dst, language=list(languages), deskew=deskew, rotate_pages=rotate,
                 pages=pages, optimize=optimize, output_type="pdf", skip_text=True, progress_bar=False)
    return dst
