"""Add text and edit existing text (plan F130–F133).

Editing works per line: the line's glyphs are removed with a text-only redaction, then the new line is
set at the same baseline in the same font (the embedded font when it has every glyph, else the matching
installed font, else a base-14 font), size and colour. The rest of the paragraph then reflows, like Foxit:
a shorter line pulls words up from the lines below it, a longer one pushes words down. Each word keeps the
font and colour it had.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

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
    block: int = -1
    words: list = field(default_factory=list)      # [(word, (font, size, color))]


def _rgb(c: int) -> tuple:
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


def lines(doc, page: int) -> list[Line]:
    """All text lines on a 1-based page, in reading order."""
    p = doc[page - 1]
    out = []
    for bn, b in enumerate(p.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT, sort=True)["blocks"]):
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            s0 = spans[0]
            out.append(Line(page, pymupdf.Rect(ln["bbox"]), "".join(s["text"] for s in ln["spans"]).rstrip(),
                            pymupdf.Point(ln["spans"][0]["origin"]), s0["font"], s0["size"], _rgb(s0["color"]),
                            s0["flags"], tuple(ln["dir"]), bn, _styled_words(ln["spans"])))
    return out


def _styled_words(spans) -> list:
    """Words of a line with the style of the span each starts in; a word split over spans stays one word."""
    words, glue = [], False
    for s in spans:
        style = (s["font"], s["size"], _rgb(s["color"]))
        parts = s["text"].split(" ")
        for k, w in enumerate(parts):
            if k > 0:
                glue = False
            if not w:
                continue
            if glue and words:
                words[-1] = (words[-1][0] + w, words[-1][1])
            else:
                words.append((w, style))
            glue = True
    return words


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
def edit_line(doc, page: int, point, new_text: str, reflow: bool = True) -> Line | None:
    """Replace the text of the line under point with new_text, keeping font, size, colour and baseline;
    with reflow, the rest of the paragraph wraps again to fill or make room."""
    ln = line_at(doc, page, point)
    if ln is None:
        raise ValueError("no text line at that position")
    p = doc[page - 1]
    if reflow and ln.dir == (1.0, 0.0):
        para = _paragraph(lines(doc, page), ln)
        if len(para) > 1:
            _reflow(doc, p, para, new_text)
            return ln
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


def _right(all_lines: list[Line], block: list[Line]) -> float:
    """Right margin of the block's column: the furthest line end among lines starting where the block's do."""
    xs = [l.rect.x0 for l in block]
    return max(l.rect.x1 for l in all_lines if any(abs(l.rect.x0 - x) < 3 for x in xs) and l.dir == block[0].dir)


def _paragraph(all_lines: list[Line], ln: Line) -> list[Line]:
    """ln and the lines after it that continue its paragraph: same block, size and left edge, and the
    line above each one was full (its first word would not have fit there, so the break was a wrap)."""
    block = [l for l in all_lines if l.block == ln.block and l.dir == ln.dir]
    right = _right(all_lines, block)
    k = next(i for i, l in enumerate(block) if l.rect == ln.rect)
    para = [ln]
    for prev, nxt in zip(block[k:], block[k + 1:]):
        if abs(nxt.size - ln.size) > 0.6 or (len(para) > 1 and abs(nxt.rect.x0 - para[1].rect.x0) > 2):
            break
        if nxt.rect.y0 - prev.rect.y1 > ln.size:                 # a gap: next paragraph
            break
        first = nxt.text.split(" ")[0]
        need = nxt.rect.width * (len(first) + 1) / max(len(nxt.text), 1)
        if prev.rect.x1 + need < right - 1:                     # it would have fit: a hard line break
            break
        para.append(nxt)
    return para


def _fonts(doc, page, words) -> dict:
    """style -> (fontname, fontfile, fontbuffer, Font) covering every word set in that style."""
    text: dict = {}
    for w, st in words:
        text[st] = text.get(st, "") + w
    out = {}
    for st, t in text.items():
        name, ffile, fbuf = _font_for(doc, page, st[0], t)
        f = pymupdf.Font(fontbuffer=fbuf) if fbuf else pymupdf.Font(fontfile=ffile) if ffile else pymupdf.Font(name)
        out[st] = (name, ffile, fbuf, f)
    return out


def _restyle(old: list, new_text: str, default) -> list:
    """Words of new_text, each keeping the style of the old word it matches (new words: the one before)."""
    new = new_text.split()
    styles = [None] * len(new)
    sm = SequenceMatcher(a=[w for w, _ in old], b=new, autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for j in range(n):
            styles[b + j] = old[a + j][1]
    out, last = [], old[0][1] if old else default
    for w, st in zip(new, styles):
        last = st or last
        out.append((w, last))
    return out


def _reflow(doc, page, para: list[Line], new_text: str):
    ln = para[0]
    all_lines = lines(doc, ln.page)
    right = _right(all_lines, [l for l in all_lines if l.block == ln.block and l.dir == ln.dir])
    words = _restyle(ln.words, new_text, (ln.font, ln.size, ln.color))
    for l in para[1:]:
        words += l.words
    fonts = _fonts(doc, page, words)

    def width(w, st):
        return fonts[st][3].text_length(w, st[1])

    step = (para[-1].origin.y - para[0].origin.y) / (len(para) - 1) if len(para) > 1 else ln.size * 1.2
    xs = [l.origin.x for l in para]
    rows: list[list] = [[]]
    x = xs[0]
    for w, st in words:
        row = len(rows) - 1
        lim = right - (xs[row] if row < len(xs) else xs[-1]) + 1
        used = x - (xs[row] if row < len(xs) else xs[-1])
        add = (width(" ", rows[-1][-1][1]) if rows[-1] else 0) + width(w, st)
        if rows[-1] and used + add > lim:
            rows.append([])
            x = xs[len(rows) - 1] if len(rows) - 1 < len(xs) else xs[-1]
            add = width(w, st)
        rows[-1].append((w, st))
        x += add
    # rows past the paragraph's last line go below it only if that space is free; else they join the last row
    while len(rows) > len(para):
        y = para[-1].origin.y + step * (len(rows) - len(para))
        band = pymupdf.Rect(xs[-1], y - ln.size * 0.7, right, y + ln.size * 0.2)     # x-height band only
        if page.get_text("words", clip=band):
            tail = rows.pop()
            rows[-1] += tail
        else:
            break
    for i, row in enumerate(rows):
        text = " ".join(w for w, _ in row)
        if i < len(para) and text == " ".join(w for w, _ in para[i].words):
            continue                                            # unchanged line: leave its glyphs alone
        if i < len(para):
            _remove_text(page, para[i].rect)
            origin = para[i].origin
        else:
            origin = pymupdf.Point(xs[-1], para[-1].origin.y + step * (i - len(para) + 1))
        runs: list[list] = []                                   # consecutive words of one style
        for k, (w, st) in enumerate(row):
            t = (" " if k else "") + w
            if runs and runs[-1][1] == st:
                runs[-1][0] += t
            else:
                runs.append([t, st])
        x = origin.x
        for t, st in runs:
            name, ffile, fbuf, f = fonts[st]
            _write(page, (x, origin.y), t, name, ffile, fbuf, st[1], st[2])
            x += f.text_length(t, st[1])
    for l in para[len(rows):]:
        _remove_text(page, l.rect)


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
            edit_line(doc, i + 1, ln.rect.tl + (ln.rect.br - ln.rect.tl) / 2, new, reflow=False)
            n += k
    return n


@command("Text.DeleteLine")
def delete_line(doc, page: int, point):
    ln = line_at(doc, page, point)
    if ln:
        _remove_text(doc[page - 1], ln.rect)
    return ln
