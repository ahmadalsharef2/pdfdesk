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


# ---- Editable text output ----------------------------------------------------------------------------------
# Foxit's "Editable Text": the scan becomes real, visible text you can edit; pictures stay as they are.

import subprocess
import tempfile
from dataclasses import dataclass

from ..core import fonts
from . import edit as edit_cmds
from .pages import parse_range

SUSPECT_BELOW = 70          # word confidence (0-100) under which a word is a suspect


@dataclass
class OcrLine:
    rect: pymupdf.Rect      # PDF points, unrotated page space
    text: str
    conf: float
    baseline: float
    words: list             # [(rect, text, conf)]
    par: tuple = ()         # (block, paragraph) ids from Tesseract
    size: float = 0.0       # font size in points, normalised per paragraph
    bold: bool = False


def _tesseract_lines(png: str, langs, dpi: int, page: pymupdf.Page, psm: int = 3) -> list[OcrLine]:
    res = subprocess.run(["tesseract", png, "stdout", "-l", "+".join(langs), "--psm", str(psm), "--dpi", str(dpi),
                          "tsv"], capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"tesseract failed: {res.stderr.strip()[:300]}")
    k = 72.0 / dpi
    groups: dict[tuple, list] = {}
    par_of: dict[tuple, tuple] = {}
    for row in res.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5" or not c[11].strip() or float(c[10]) < 0:
            continue
        x, y, w, h = (int(v) for v in c[6:10])
        r = pymupdf.Rect(x * k, y * k, (x + w) * k, (y + h) * k)
        r = pymupdf.Rect(pymupdf.Point(r.tl) * page.derotation_matrix, pymupdf.Point(r.br) * page.derotation_matrix)
        r.normalize()
        groups.setdefault((c[2], c[3], c[4]), []).append((r, c[11].strip(), float(c[10])))
        par_of[(c[2], c[3], c[4])] = (c[2], c[3])
    lines = []
    for key, words in groups.items():
        rect = pymupdf.Rect()
        for r, _t, _c in words:
            rect |= r
        text = " ".join(t for _r, t, _c in words)
        conf = sum(c for _r, _t, c in words) / len(words)
        flat = [r.y1 for r, t, _c in words if not any(ch in t for ch in "gjpqy,;()[]{}|Qy")]
        base = sorted(flat)[len(flat) // 2] if flat else rect.y1 - rect.height * 0.22
        lines.append(OcrLine(rect, text, conf, base, words, par_of[key]))
    _normalise_sizes(lines)
    lines.sort(key=lambda ln: (round(ln.rect.y0 / 8), ln.rect.x0))
    return lines


def _normalise_sizes(lines: list[OcrLine]):
    """Line boxes vary with ascenders/descenders, so use the paragraph's median size unless a line really differs
    (a heading is more than 25% larger)."""
    by_par: dict[tuple, list[OcrLine]] = {}
    for ln in lines:
        ln.size = max(4.0, min(ln.rect.height / 1.2, 72))
        by_par.setdefault(ln.par, []).append(ln)
    for group in by_par.values():
        med = sorted(g.size for g in group)[len(group) // 2]
        for g in group:
            if abs(g.size - med) / med < 0.25:
                g.size = med


def _sample_colors(arr, rect_px):
    """(background rgb, text rgb) for a line, from pixels: ring around the box and the darkest pixels in it."""
    import numpy as np
    x0, y0, x1, y1 = rect_px
    H, W, _ = arr.shape
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    pad = 3
    parts = [arr[max(0, y0 - pad):y0, x0:x1], arr[y1:min(H, y1 + pad), x0:x1],
             arr[y0:y1, max(0, x0 - pad):x0], arr[y0:y1, x1:min(W, x1 + pad)]]
    ring = np.concatenate([p.reshape(-1, 3) for p in parts if p.size]) if any(p.size for p in parts) else None
    box = arr[y0:y1, x0:x1].reshape(-1, 3)
    bg = np.median(ring if ring is not None and len(ring) else box, axis=0)
    lum = box @ np.array([0.299, 0.587, 0.114])
    n = max(1, int(len(lum) * 0.06))
    dark = box[np.argsort(lum)[:n]].mean(axis=0)
    if abs(float(bg @ np.array([0.299, 0.587, 0.114])) - float(dark @ np.array([0.299, 0.587, 0.114]))) < 50:
        dark = np.array([0, 0, 0])
    return tuple(float(v) / 255 for v in bg), tuple(float(v) / 255 for v in dark)


def _write_line(page, ln: OcrLine, fontfile, color, boldfile=None):
    text, r = ln.text, ln.rect
    if edit_cmds.RTL.search(text):
        edit_cmds.add_text(page.parent, page.number + 1, (r.x0, r.y0), text, fontsize=max(6, r.height * 0.8),
                           color=color, width=r.width)
        return
    fontfile = boldfile if (ln.bold and boldfile) else fontfile
    f = pymupdf.Font(fontfile=fontfile)
    size = ln.size or max(4.0, min(r.height / 1.2, 72))
    nat = f.text_length(text, size)
    k = r.width / nat if nat else 1
    if k < 0.85:                       # text would be much wider than the line: shrink, then scale to fit
        size *= k
        nat = f.text_length(text, size)
        k = r.width / nat if nat else 1
    k = max(0.8, min(k, 1.25))
    origin = pymupdf.Point(r.x0, ln.baseline)
    page.insert_text(origin, text, fontname="ocrbold" if fontfile == boldfile else "ocrfont", fontfile=fontfile, fontsize=size, color=color,
                     morph=(origin, pymupdf.Matrix(k, 0, 0, 1, 0, 0)))


@command("Ocr.Editable")
def ocr_editable(doc: pymupdf.Document, languages=("eng",), pages: str | None = None, dpi: int = 300,
                 progress=None, min_conf: float = 0) -> dict:
    """Turn scanned pages into real text, in place. Pages that already have text are left alone.
    Returns {'pages': n, 'lines': n, 'suspects': [{'page','rect','text','conf'}]}."""
    import numpy as np
    fontfile = fonts.find("Liberation Sans") or fonts.unicode_font()
    boldfile = fonts.find("Liberation Sans", bold=True)
    stats = {"pages": 0, "lines": 0, "suspects": []}
    idx = parse_range(pages, doc.page_count)
    for n, i in enumerate(idx):
        page = doc[i]
        if progress:
            progress(n, len(idx))
        if page.get_text().strip():
            continue
        pm = page.get_pixmap(dpi=dpi, alpha=False)
        arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3)
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            pm.save(f.name)
            lines = _tesseract_lines(f.name, languages, dpi, page)
        s = dpi / 72.0
        derot = ~page.derotation_matrix
        gray = arr @ np.array([0.299, 0.587, 0.114])
        ink: list[float] = []
        for ln in lines:
            rp = pymupdf.Rect(ln.rect * derot).normalize()
            box = gray[max(0, int(rp.y0 * s)):int(rp.y1 * s), max(0, int(rp.x0 * s)):int(rp.x1 * s)]
            ink.append(float((box < 128).mean()) if box.size else 0.0)
        med_ink = sorted(ink)[len(ink) // 2] if ink else 0
        for ln, v in zip(lines, ink):
            ln.bold = bool(med_ink) and v > med_ink * 1.35 and ln.size >= 7
        for ln in lines:
            if not ln.text.strip() or ln.conf < min_conf:
                continue
            rp = pymupdf.Rect(ln.rect * derot).normalize()
            bg, fg = _sample_colors(arr, (int(rp.x0 * s) - 1, int(rp.y0 * s) - 1, int(rp.x1 * s) + 1, int(rp.y1 * s) + 1))
            page.draw_rect(ln.rect + (-1.0, -0.8, 1.0, 0.8), color=None, fill=bg, overlay=True)
            _write_line(page, ln, fontfile, fg, boldfile)
            stats["lines"] += 1
            for wr, wt, wc in ln.words:
                if wc < SUSPECT_BELOW:
                    stats["suspects"].append({"page": i + 1, "rect": tuple(wr), "text": wt, "conf": wc})
        stats["pages"] += 1
    return stats
