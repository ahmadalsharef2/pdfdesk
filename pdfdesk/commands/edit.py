"""Add text and edit existing text (plan F130–F133).

Editing works per line: the line's glyphs are removed with a text-only redaction, then the new line is
set at the same baseline in the same font (the embedded font when it has every glyph, else the matching
installed font, else a base-14 font), size and colour.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pymupdf

from ..core import fonts
from .registry import command


@dataclass
class Line:
    page: int
    rect: pymupdf.Rect
    text: str
    origin: pymupdf.Point
    font: str
    size: float
    color: tuple
    flags: int
    dir: tuple


def _rgb(c: int) -> tuple:
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


def lines(doc, page: int) -> list[Line]:
    """All text lines on a 1-based page, in reading order."""
    p = doc[page - 1]
    out = []
    for b in p.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT, sort=True)["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            s0 = spans[0]
            out.append(Line(page, pymupdf.Rect(ln["bbox"]), "".join(s["text"] for s in ln["spans"]).rstrip(),
                            pymupdf.Point(ln["spans"][0]["origin"]), s0["font"], s0["size"], _rgb(s0["color"]),
                            s0["flags"], tuple(ln["dir"])))
    return out


def line_at(doc, page: int, point) -> Line | None:
    pt = pymupdf.Point(point)
    best = None
    for ln in lines(doc, page):
        r = ln.rect + (-2, -2, 2, 2)
        if r.contains(pt):
            if best is None or ln.rect.get_area() < best.rect.get_area():
                best = ln
    return best


BASE14 = {"Helvetica": "helv", "Helvetica-Bold": "hebo", "Helvetica-Oblique": "heit",
          "Helvetica-BoldOblique": "hebi", "Times-Roman": "tiro", "Times-Bold": "tibo", "Times-Italic": "tiit",
          "Times-BoldItalic": "tibi", "Courier": "cour", "Courier-Bold": "cobo", "Courier-Oblique": "coit",
          "Courier-BoldOblique": "cobi", "Symbol": "symb", "ZapfDingbats": "zadb"}


def _font_for(doc, page: pymupdf.Page, pdf_font: str, text: str) -> tuple[str, str | None, bytes | None]:
    """Return (fontname to use, fontfile, fontbuffer)."""
    base14 = BASE14.get(pdf_font.split("+")[-1])
    if base14 and all(ord(ch) < 256 for ch in text):
        return base14, None, None
    # 1. embedded font program, if it covers every character
    for xref, ext, _type, basefont, _name, _enc in page.get_fonts():
        if basefont == pdf_font or basefont.split("+")[-1] == pdf_font.split("+")[-1]:
            try:
                _bn, fext, _t, buf = doc.extract_font(xref)
            except Exception:  # noqa: BLE001
                buf = b""
            if buf and fext in ("ttf", "otf", "cff", "pfa", "pfb", "n/a") and fext != "n/a":
                try:
                    f = pymupdf.Font(fontbuffer=buf)
                    if all(f.has_glyph(ord(ch)) for ch in text if not ch.isspace()):
                        return f"E{xref}", None, buf
                except Exception:  # noqa: BLE001
                    pass
            break
    # 2. installed font of the same family/style
    path, base = fonts.for_pdf_font(pdf_font)
    if path:
        f = pymupdf.Font(fontfile=path)
        if all(f.has_glyph(ord(ch)) for ch in text if not ch.isspace()):
            return "F" + str(abs(hash(path)) % 10**8), path, None
    # 3. base-14 if it can encode the text, else a Unicode font
    if all(ord(ch) < 256 for ch in text):
        return base, None, None
    uf = fonts.unicode_font()
    return "U" + str(abs(hash(uf)) % 10**8), uf, None


def _without_other_redactions(page, fn):
    """apply_redactions applies every Redact annot on the page; keep the user's own marks out of it."""
    saved = []
    for a in list(page.annots(types=[pymupdf.PDF_ANNOT_REDACT]) or []):
        doc = page.parent
        ov = doc.xref_get_key(a.xref, "OverlayText")
        saved.append((a.rect, ov[1].strip("()") if ov[0] == "string" else None, a.colors.get("fill")))
        page.delete_annot(a)
    fn()
    for rect, text, fill in saved:
        page.add_redact_annot(rect, text=text, fill=fill, cross_out=False)


def _remove_text(page, rect):
    # shrink a little so glyphs of neighbouring lines that merely touch are kept
    r = pymupdf.Rect(rect)
    h = r.height
    r = pymupdf.Rect(r.x0 - 0.5, r.y0 + h * 0.15, r.x1 + 0.5, r.y1 - h * 0.15)

    def go():
        page.add_redact_annot(r, fill=False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    _without_other_redactions(page, go)


def _write(page, origin, text, fontname, fontfile, fontbuffer, size, color, rotate=0):
    if not text:
        return
    if fontfile or fontbuffer:
        page.insert_font(fontname=fontname, fontfile=fontfile, fontbuffer=fontbuffer)
    page.insert_text(origin, text, fontname=fontname, fontsize=size, color=color, rotate=rotate)


RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")


@command("Text.Add")
def add_text(doc, page: int, point, text: str, fontsize: float = 12, color=(0, 0, 0), font: str | None = None,
             width: float | None = None):
    """Add new text with its top-left at point (PDF units). An HTML box shapes and wraps any script;
    right-to-left text (Arabic, Hebrew) uses an installed font whose ToUnicode map extracts correctly."""
    p = doc[page - 1]
    x, y = pymupdf.Point(point)
    rtl = bool(RTL.search(text))
    ffile = (fonts.find("Noto Sans Arabic") or fonts.unicode_font()) if rtl else (font and fonts.find(font))
    measure = pymupdf.Font(fontfile=ffile) if ffile else pymupdf.Font("helv")
    rows = text.split("\n")
    natural = max(measure.text_length(r, fontsize) for r in rows) * 1.15 + fontsize
    w = width or min(natural, max(50, p.rect.width - x - 10))
    rect = pymupdf.Rect(x, y, x + w, y + fontsize * 1.5 * len(rows) + fontsize)
    r, g, b = (int(c * 255) for c in color)
    archive, face = None, "sans-serif"
    if ffile:
        archive = pymupdf.Archive(os.path.dirname(ffile))
        face = f"pdfdeskface, sans-serif"
    css = (f"@font-face {{font-family: pdfdeskface; src: url({os.path.basename(ffile)});}} " if ffile else "") + \
          f"* {{font-family: {face}; font-size: {fontsize}px; color: rgb({r},{g},{b}); margin: 0;}}"
    html = "<br>".join(_esc(t) for t in rows)
    if rtl:
        html = f'<div dir="rtl">{html}</div>'
    for _ in range(4):
        spare, _scale = p.insert_htmlbox(rect, html, css=css, archive=archive, scale_low=1)
        if spare >= 0:
            break
        rect.y1 += fontsize * 2
    return rect


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@command("Text.EditLine")
def edit_line(doc, page: int, point, new_text: str) -> Line | None:
    """Replace the text of the line under point with new_text, keeping font, size, colour and baseline."""
    ln = line_at(doc, page, point)
    if ln is None:
        raise ValueError("no text line at that position")
    p = doc[page - 1]
    fontname, ffile, fbuf = _font_for(doc, p, ln.font, new_text)
    _remove_text(p, ln.rect)
    rot = 0
    dx, dy = ln.dir
    if abs(dx) < 0.5:
        rot = 90 if dy < 0 else 270
    elif dx < 0:
        rot = 180
    _write(p, ln.origin, new_text, fontname, ffile, fbuf, ln.size, ln.color, rotate=rot)
    return ln


@command("Text.Replace")
def replace_text(doc, find: str, replace: str, pages: str | None = None, case_sensitive: bool = True) -> int:
    """Find and replace across the document, line by line. Returns the number of replacements."""
    from .pages import parse_range
    import re
    n = 0
    rx = re.compile(re.escape(find), 0 if case_sensitive else re.I)
    for i in parse_range(pages, doc.page_count):
        for ln in [l for l in lines(doc, i + 1) if rx.search(l.text)]:
            new, k = rx.subn(replace, ln.text)
            edit_line(doc, i + 1, ln.rect.tl + (ln.rect.br - ln.rect.tl) / 2, new)
            n += k
    return n


@command("Text.DeleteLine")
def delete_line(doc, page: int, point):
    ln = line_at(doc, page, point)
    if ln:
        _remove_text(doc[page - 1], ln.rect)
    return ln
