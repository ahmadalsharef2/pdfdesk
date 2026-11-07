"""OCR with PaddleOCR: a searchable text layer under the scan, or editable text in place of it.
Auto Redact uses page_lines() to read scanned pages."""
from __future__ import annotations

import functools
import logging
import os
import sys
import warnings
from dataclasses import dataclass

import pymupdf

from ..core import fonts
from . import edit as edit_cmds
from .pages import parse_range
from .registry import command

SUSPECT_BELOW = 70          # line confidence (0-100) under which its words are suspects
# Paddle has one recogniser per language; older Tesseract-style codes are accepted too
LANG_CODES = {"eng": "en", "deu": "de", "ger": "de", "german": "de", "ara": "ar", "arabic": "ar", "fra": "fr",
              "spa": "es", "ita": "it", "chi_sim": "ch"}


def is_scanned(doc: pymupdf.Document, page: int = 0) -> bool:
    p = doc[page]
    if p.get_text().strip():
        return False
    return any(pymupdf.Rect(i["bbox"]).get_area() >= 0.9 * p.rect.get_area() for i in p.get_image_info())


def paddle_lang(languages) -> str:
    """One Paddle language for a list of codes: Arabic wins (its model also reads Latin letters and digits),
    several Latin-script languages share the 'latin' model."""
    codes = {LANG_CODES.get(c.strip().lower(), c.strip().lower()) for c in languages if c.strip()} or {"en"}
    if "ar" in codes:
        return "ar"
    return codes.pop() if len(codes) == 1 else "latin"


def _point_paddle_at_its_libs():
    """Paddle looks for MKL in its site-packages folder, which a frozen app does not have; it also reads the
    folder from FLAGS_mklml_dir, so set that before Paddle loads."""
    os.environ.setdefault("FLAGS_mklml_dir", os.path.join(sys._MEIPASS, "paddle", "libs"))


@functools.lru_cache(maxsize=2)
def _engine(lang: str):
    """Loading the models takes seconds, so keep one engine per language. The first use downloads them to
    ~/.paddlex. Needs paddlepaddle 3.2: 3.3's oneDNN kernels reject the models, and without oneDNN a page
    takes ~45 s. The detector works on at most 2000 px, which bounds memory."""
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if getattr(sys, "frozen", False):
            _point_paddle_at_its_libs()
        from paddleocr import PaddleOCR
    logging.getLogger("paddlex").setLevel(logging.ERROR)
    return PaddleOCR(lang=lang, use_doc_orientation_classify=False, use_doc_unwarping=False,
                     use_textline_orientation=False, text_det_limit_side_len=2000, text_det_limit_type="max")


@dataclass
class OcrLine:
    rect: pymupdf.Rect      # PDF points, unrotated page space
    text: str
    conf: float             # 0-100
    baseline: float
    words: list             # [(rect, text, conf)]
    par: int = 0            # paragraph number, from line spacing
    size: float = 0.0       # font size in points, normalised per paragraph
    bold: bool = False


def _words(tokens, regions) -> list[tuple[str, tuple]]:
    """Paddle splits a line into tokens ("jane", ".", "doe", ", ", "call"); join them into words at spaces."""
    out, cur, box = [], "", None
    for tok, reg in zip(tokens, regions):
        xs, ys = [q[0] for q in reg], [q[1] for q in reg]
        r = (min(xs), min(ys), max(xs), max(ys))
        for n, part in enumerate(tok.split(" ")):
            if n and cur:
                out.append((cur, box))
                cur, box = "", None
            if part:
                cur += part
                box = r if box is None else (min(box[0], r[0]), min(box[1], r[1]), max(box[2], r[2]), max(box[3], r[3]))
    if cur:
        out.append((cur, box))
    return out


def _paddle_lines(rgb, languages, dpi: int, page: pymupdf.Page) -> list[OcrLine]:
    res = _engine(paddle_lang(languages)).predict(rgb[:, :, ::-1], return_word_box=True)[0]
    k = 72.0 / dpi
    derot = page.derotation_matrix

    def to_page(x0, y0, x1, y1):
        return pymupdf.Rect(pymupdf.Point(x0 * k, y0 * k) * derot, pymupdf.Point(x1 * k, y1 * k) * derot).normalize()
    lines = []
    for text, score, box, toks, regs in zip(res["rec_texts"], res["rec_scores"], res["rec_boxes"],
                                            res["text_word"], res["text_word_region"]):
        if not text.strip():
            continue
        conf = float(score) * 100
        rect = to_page(*(float(v) for v in box))
        words = [(to_page(*b), w, conf) for w, b in _words(toks, regs)] or [(rect, text.strip(), conf)]
        lines.append(OcrLine(rect, text.strip(), conf, rect.y1 - rect.height * 0.22, words))
    lines.sort(key=lambda ln: (round(ln.rect.y0 / 8), ln.rect.x0))
    _paragraphs(lines)
    _normalise_sizes(lines)
    return lines


def _paragraphs(lines: list[OcrLine]):
    """Number paragraphs: a line continues the one above when it is about as tall, close below it and overlaps
    it sideways."""
    par, prev = 0, None
    for ln in sorted(lines, key=lambda ln: ln.rect.y0):
        h = ln.rect.height
        if not (prev and abs(h - prev.rect.height) < 0.25 * h and 0 <= ln.rect.y0 - prev.rect.y1 < 0.8 * h
                and min(ln.rect.x1, prev.rect.x1) > max(ln.rect.x0, prev.rect.x0)):
            par += 1
        ln.par, prev = par, ln


def _render_lines(page: pymupdf.Page, languages, dpi: int):
    """(pixels as an RGB array, OCR lines) for one page."""
    import numpy as np
    pm = page.get_pixmap(dpi=dpi, alpha=False)
    rgb = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3)
    return rgb, _paddle_lines(rgb, languages, dpi, page)


def page_lines(page: pymupdf.Page, languages=("en",), dpi: int = 300, every_script: bool = False) -> list[OcrLine]:
    """OCR lines and word boxes for one page, in page coordinates. every_script: with Arabic and Latin
    languages, read the page with both models (the Arabic one garbles e-mail addresses in Arabic lines);
    the lines then overlap, which is fine for finding things but not for writing text."""
    rgb, lines = _render_lines(page, languages, dpi)
    others = [c for c in languages if paddle_lang([c]) != "ar"]
    if every_script and paddle_lang(languages) == "ar" and others:
        lines += _paddle_lines(rgb, others, dpi, page)
    return lines


# ---- Searchable text: an invisible text layer over the scan --------------------------------------------------
@command("Ocr.Searchable")
def ocr_searchable(doc: pymupdf.Document, languages=("en",), pages: str | None = None, dpi: int = 300,
                   progress=None) -> dict:
    """Add invisible text over each scanned page, in place, so it can be searched, selected and copied.
    Pages that already have text are left alone. Returns {'pages': n, 'lines': n}."""
    fontfile = fonts.unicode_font()
    font = pymupdf.Font(fontfile=fontfile)
    stats = {"pages": 0, "lines": 0}
    idx = parse_range(pages, doc.page_count)
    for n, i in enumerate(idx):
        if progress:
            progress(n, len(idx))
        page = doc[i]
        if page.get_text().strip():
            continue
        for ln in page_lines(page, languages, dpi):
            for r, w, _c in ln.words:
                size = max(2.0, r.height * 0.8)
                width = font.text_length(w, size) or 1
                origin = pymupdf.Point(r.x0, r.y1 - r.height * 0.2)
                page.insert_text(origin, w, fontsize=size, fontname="ocrtext", fontfile=fontfile, render_mode=3,
                                 morph=(origin, pymupdf.Matrix(r.width / width, 0, 0, 1, 0, 0)))
            stats["lines"] += 1
        stats["pages"] += 1
    return stats


@command("Ocr.Run")
def ocr(src: str, dst: str, languages=("en",), pages: str | None = None):
    """Ocr.Searchable from one file to another."""
    doc = pymupdf.open(src)
    ocr_searchable(doc, languages, pages)
    doc.save(dst, garbage=3, deflate=True)
    return dst


# ---- Editable text output ----------------------------------------------------------------------------------
# Foxit's "Editable Text": the scan becomes real, visible text you can edit; pictures stay as they are.

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
def ocr_editable(doc: pymupdf.Document, languages=("en",), pages: str | None = None, dpi: int = 300,
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
        arr, lines = _render_lines(page, languages, dpi)
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
