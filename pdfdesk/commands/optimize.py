"""PDF Optimizer (Foxit's Reduce File Size and the advanced optimizer), audit of space usage."""
from __future__ import annotations

import os

import pymupdf

from .registry import command

PRESETS = {  # dpi threshold, target dpi, JPEG quality
    "high": (300, 200, 85), "medium": (225, 150, 75), "low": (150, 96, 60), "minimum": (110, 72, 45),
}


@command("Optimize.Reduce")
def reduce(doc, quality: str = "medium", images: bool = True, subset_fonts: bool = True,
           remove_metadata: bool = False, remove_thumbnails: bool = True, remove_attachments: bool = False,
           remove_javascript: bool = False, remove_links: bool = False, grayscale: bool = False):
    """Downsample and recompress images above the preset's threshold, subset embedded fonts, drop page
    thumbnails and optional data. The caller saves with garbage=4, deflate=True to write the result."""
    if images:
        thr, dpi, q = PRESETS[quality]
        doc.rewrite_images(dpi_threshold=thr, dpi_target=dpi, quality=q, lossy=True, lossless=True,
                           bitonal=True, color=True, gray=True, set_to_gray=grayscale)
    if subset_fonts:
        try:
            doc.subset_fonts()
        except Exception:  # noqa: BLE001  (fontTools may reject an odd font; the rest still applies)
            pass
    if remove_thumbnails:
        for page in doc:
            if doc.xref_get_key(page.xref, "Thumb")[0] != "null":
                doc.xref_set_key(page.xref, "Thumb", "null")
    if remove_metadata or remove_attachments or remove_javascript or remove_links:
        doc.scrub(attached_files=remove_attachments, clean_pages=False, embedded_files=remove_attachments,
                  hidden_text=False, javascript=remove_javascript, metadata=remove_metadata,
                  redactions=False, redact_images=0, remove_links=remove_links, reset_fields=False,
                  reset_responses=False, thumbnails=remove_thumbnails, xml_metadata=remove_metadata)


@command("Optimize.Audit")
def audit(doc) -> dict:
    """Foxit's "Audit space usage": bytes per object kind."""
    kinds = {"Images": 0, "Fonts": 0, "Content streams": 0, "Forms (XObjects)": 0, "Embedded files": 0,
             "Other streams": 0}
    for x in range(1, doc.xref_length()):
        if not doc.xref_is_stream(x):
            continue
        try:
            n = len(doc.xref_stream_raw(x) or b"")
        except Exception:  # noqa: BLE001
            continue
        sub = doc.xref_get_key(x, "Subtype")[1]
        typ = doc.xref_get_key(x, "Type")[1]
        if sub == "/Image":
            kinds["Images"] += n
        elif doc.xref_get_key(x, "Length1")[0] != "null" or sub in ("/Type1C", "/CIDFontType0C", "/OpenType"):
            kinds["Fonts"] += n
        elif sub == "/Form":
            kinds["Forms (XObjects)"] += n
        elif typ == "/EmbeddedFile":
            kinds["Embedded files"] += n
        else:
            kinds["Other streams"] += n
    contents = set()
    for page in doc:
        contents.update(page.get_contents())
    c = sum(len(doc.xref_stream_raw(x) or b"") for x in contents)
    kinds["Content streams"] = c
    kinds["Other streams"] = max(0, kinds["Other streams"] - c)
    return kinds


@command("Optimize.File")
def optimize_file(src: str, dst: str, quality: str = "medium", **opts) -> tuple[int, int]:
    """Optimize a file on disk; returns (size before, size after)."""
    doc = pymupdf.open(src)
    reduce(doc, quality, **opts)
    doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True,
             use_objstms=True)
    return os.path.getsize(src), os.path.getsize(dst)
