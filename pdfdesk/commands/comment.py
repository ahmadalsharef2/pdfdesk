"""Comment tools (plan phase 9): the Comment ribbon tab. Coordinates are PDF points, unrotated page space,
pages are 1-based. Every function returns the created annotation's xref."""
from __future__ import annotations

import html
import re

import pymupdf

from .registry import command

YELLOW, RED, BLUE = (1, 0.85, 0), (0.9, 0.1, 0.1), (0.1, 0.3, 0.9)
# the color each GUI tool gives a new comment unless the user picks another (typewriter: its text color)
DEFAULT_COLORS = {"highlight": YELLOW, "area-highlight": YELLOW, "underline": (0, 0.6, 0), "strikeout": RED,
                  "squiggly": BLUE, "note": YELLOW, "typewriter": (0, 0, 0),
                  **{t: RED for t in ("rectangle", "oval", "line", "arrow", "polygon", "cloud", "polyline", "pencil")}}


def _finish(annot, author: str | None, content: str | None = None, color=None, fill=None, width=None,
            opacity=None):
    if color is not None or fill is not None:
        annot.set_colors(stroke=color, fill=fill)
    if width is not None:
        annot.set_border(width=width)
    if opacity is not None:
        annot.set_opacity(opacity)
    info = {}
    if author:
        info["title"] = author
    if content is not None:
        info["content"] = content
    if info:
        annot.set_info(**info)
    annot.update()
    return annot.xref


# ---- text markup ----------------------------------------------------------------------------------
def text_between(page: pymupdf.Page, start, stop, words=None) -> list[tuple[pymupdf.Rect, str]]:
    """The text flow from the word at start to the word at stop, as (line box, line text), in reading order.
    Either point may come first; a point off the text takes the nearest word, preferring its own line.
    words: the page's get_text("words"), when the caller keeps it."""
    words = page.get_text("words") if words is None else words
    if not words:
        return []

    def gap(lo, hi, v):
        return max(lo - v, 0, v - hi)

    def nearest(pt):
        pt = pymupdf.Point(pt)
        same = [k for k, w in enumerate(words) if w[1] - 2 <= pt.y <= w[3] + 2]
        if same:
            return min(same, key=lambda k: gap(words[k][0], words[k][2], pt.x))
        return min(range(len(words)), key=lambda k: gap(words[k][1], words[k][3], pt.y) * 4 +
                   gap(words[k][0], words[k][2], pt.x))

    a, b = sorted((nearest(start), nearest(stop)))
    out: list[tuple[pymupdf.Rect, str]] = []
    key = None
    for w in words[a:b + 1]:
        if (w[5], w[6]) != key:
            key = (w[5], w[6])
            out.append((pymupdf.Rect(w[:4]), w[4]))
        else:
            out[-1] = (out[-1][0] | pymupdf.Rect(w[:4]), out[-1][1] + " " + w[4])
    return out


def _markup(kind, doc, page, start, stop, author, color, note):
    p = doc[page - 1]
    fn = {"highlight": p.add_highlight_annot, "underline": p.add_underline_annot,
          "strikeout": p.add_strikeout_annot, "squiggly": p.add_squiggly_annot}[kind]
    sel = text_between(p, start, stop)
    if not sel:
        raise ValueError("no text on this page to mark up")
    a = fn(quads=[r.quad for r, _t in sel])
    if a is None:
        raise ValueError("no text between those points")
    return _finish(a, author, note, color=color)


@command("Comment.Highlight")
def highlight(doc, page, start, stop, author=None, color=YELLOW, note=None):
    return _markup("highlight", doc, page, start, stop, author, color, note)


@command("Comment.Underline")
def underline(doc, page, start, stop, author=None, color=(0, 0.6, 0), note=None):
    return _markup("underline", doc, page, start, stop, author, color, note)


@command("Comment.Strikeout")
def strikeout(doc, page, start, stop, author=None, color=RED, note=None):
    return _markup("strikeout", doc, page, start, stop, author, color, note)


@command("Comment.Squiggly")
def squiggly(doc, page, start, stop, author=None, color=BLUE, note=None):
    return _markup("squiggly", doc, page, start, stop, author, color, note)


@command("Comment.ReplaceText")
def replace_text(doc, page, start, stop, replacement: str, author=None):
    """Foxit 'Replace Text': strike out the selection and attach a caret with the replacement."""
    x = strikeout(doc, page, start, stop, author, note=f"Replace with: {replacement}")
    caret = (p := doc[page - 1]).add_caret_annot(pymupdf.Point(max(pymupdf.Point(start).x, pymupdf.Point(stop).x),
                                                       pymupdf.Point(stop).y))
    _finish(caret, author, replacement, color=BLUE)
    return x


@command("Comment.InsertText")
def insert_text(doc, page, point, text: str, author=None):
    a = (p := doc[page - 1]).add_caret_annot(pymupdf.Point(point))
    return _finish(a, author, text, color=BLUE)


@command("Comment.AreaHighlight")
def area_highlight(doc, page, rect, author=None, color=YELLOW):
    r = pymupdf.Rect(rect)
    a = (p := doc[page - 1]).add_highlight_annot(quads=[r.quad])
    return _finish(a, author, color=color)


# ---- pin -------------------------------------------------------------------------------------------
@command("Comment.Note")
def note(doc, page, point, text: str, author=None, icon="Note", color=YELLOW):
    a = (p := doc[page - 1]).add_text_annot(pymupdf.Point(point), text, icon=icon)
    return _finish(a, author, color=color)


@command("Comment.File")
def file_attachment(doc, page, point, path: str, author=None, description=None):
    with open(path, "rb") as f:
        data = f.read()
    name = path.rsplit("/", 1)[-1]
    a = (p := doc[page - 1]).add_file_annot(pymupdf.Point(point), data, name, desc=description or name)
    return _finish(a, author)


# ---- typewriter ------------------------------------------------------------------------------------
@command("Comment.Typewriter")
def typewriter(doc, page, point, text: str, fontsize=12, color=(0, 0, 0), author=None):
    p = doc[page - 1]
    x, y = pymupdf.Point(point)
    rows = text.split("\n")
    w = max(pymupdf.get_text_length(r, "helv", fontsize) for r in rows) + fontsize
    rect = pymupdf.Rect(x, y, min(x + w, p.rect.width), y + fontsize * 1.3 * len(rows) + 4)
    a = p.add_freetext_annot(rect, text, fontsize=fontsize, fontname="helv", text_color=color, border_width=0)
    doc.xref_set_key(a.xref, "IT", "/FreeTextTypeWriter")
    return _finish(a, author)


def _rich(text: str) -> str:
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join(f"<p>{ln or '&#160;'}</p>" for ln in esc.split("\n"))


def _rich_body(text: str) -> str:
    """A whole RC value, as MuPDF writes it, for replacing a text box's text."""
    return ('<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xtml" '
            'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" xfa:contentType="text/html" '
            f'xfa:APIVersion="Acrobat:8.0.0" xfa:spec="2.4">{_rich(text)}</body>')


@command("Comment.Textbox")
def textbox(doc, page, rect, text: str, fontsize=11, author=None, border=RED, fill=(1, 1, 1)):
    a = (p := doc[page - 1]).add_freetext_annot(pymupdf.Rect(rect), _rich(text), fontsize=fontsize,
                                                text_color=(0, 0, 0), border_color=border, fill_color=fill,
                                                border_width=1, richtext=True)
    return _finish(a, author, text)


@command("Comment.Callout")
def callout(doc, page, target, rect, text: str, fontsize=11, author=None, border=RED):
    """target: the point the leader line points at; rect: the text box."""
    r = pymupdf.Rect(rect)
    t = pymupdf.Point(target)
    knee = pymupdf.Point(r.x0 - 15 if t.x < r.x0 else r.x1 + 15, (r.y0 + r.y1) / 2)
    edge = pymupdf.Point(r.x0 if t.x < r.x0 else r.x1, knee.y)
    a = (p := doc[page - 1]).add_freetext_annot(r, _rich(text), fontsize=fontsize, text_color=(0, 0, 0),
                                                border_color=border, fill_color=(1, 1, 1), border_width=1,
                                                callout=(t, knee, edge), line_end=pymupdf.PDF_ANNOT_LE_OPEN_ARROW,
                                                richtext=True)
    return _finish(a, author, text)


# ---- drawing --------------------------------------------------------------------------------------
@command("Comment.Rectangle")
def rectangle(doc, page, rect, author=None, color=RED, fill=None, width=1.5):
    return _finish((p := doc[page - 1]).add_rect_annot(pymupdf.Rect(rect)), author, color=color, fill=fill, width=width)


@command("Comment.Oval")
def oval(doc, page, rect, author=None, color=RED, fill=None, width=1.5):
    return _finish((p := doc[page - 1]).add_circle_annot(pymupdf.Rect(rect)), author, color=color, fill=fill, width=width)


@command("Comment.Line")
def line(doc, page, p1, p2, author=None, color=RED, width=1.5, arrow=False):
    a = (p := doc[page - 1]).add_line_annot(pymupdf.Point(p1), pymupdf.Point(p2))
    if arrow:
        a.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
    return _finish(a, author, color=color, width=width)


@command("Comment.Arrow")
def arrow(doc, page, p1, p2, author=None, color=RED, width=1.5):
    return line(doc, page, p1, p2, author, color, width, arrow=True)


@command("Comment.Polygon")
def polygon(doc, page, points, author=None, color=RED, fill=None, width=1.5, cloud=False):
    a = (p := doc[page - 1]).add_polygon_annot([pymupdf.Point(p) for p in points])
    if cloud:
        a.set_border(width=width, clouds=2)
    return _finish(a, author, color=color, fill=fill, width=None if cloud else width)


@command("Comment.Cloud")
def cloud(doc, page, points, author=None, color=RED, width=1.5):
    return polygon(doc, page, points, author, color, None, width, cloud=True)


@command("Comment.Polyline")
def polyline(doc, page, points, author=None, color=RED, width=1.5):
    a = (p := doc[page - 1]).add_polyline_annot([pymupdf.Point(p) for p in points])
    return _finish(a, author, color=color, width=width)


@command("Comment.Pencil")
def pencil(doc, page, strokes, author=None, color=RED, width=1.5):
    """strokes: list of lists of points."""
    a = (p := doc[page - 1]).add_ink_annot([[tuple(pymupdf.Point(p)) for p in s] for s in strokes])
    return _finish(a, author, color=color, width=width)


STAMPS = {"Approved": 0, "AsIs": 1, "Confidential": 2, "Departmental": 3, "Experimental": 4, "Expired": 5,
          "Final": 6, "ForComment": 7, "ForPublicRelease": 8, "NotApproved": 9, "NotForPublicRelease": 10,
          "Sold": 11, "TopSecret": 12, "Draft": 13}


@command("Comment.Stamp")
def stamp(doc, page, rect, name="Approved", author=None):
    a = (p := doc[page - 1]).add_stamp_annot(pymupdf.Rect(rect), stamp=getattr(pymupdf, f"STAMP_{name}", STAMPS.get(name, 0)))
    return _finish(a, author)


# ---- managing ---------------------------------------------------------------------------------------
@command("Comment.List")
def list_comments(doc):
    out = []
    for p in doc:
        for a in p.annots() or []:
            if a.type[0] in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_POPUP):
                continue
            out.append({"page": p.number + 1, "xref": a.xref, "type": a.type[1], "author": a.info.get("title", ""),
                        "content": a.info.get("content", ""), "rect": tuple(a.rect)})
    return out


@command("Comment.At")
def annot_at(doc, page, point):
    pt = pymupdf.Point(point)
    p = doc[page - 1]
    best = None
    for a in p.annots() or []:
        if a.type[0] in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_POPUP):
            continue
        if (a.rect + (-3, -3, 3, 3)).contains(pt) and (best is None or a.rect.get_area() < best.rect.get_area()):
            best = a
    return best.xref if best else None


@command("Comment.Delete")
def delete(doc, page, xref: int):
    p = doc[page - 1]
    for a in p.annots() or []:
        if a.xref == xref:
            p.delete_annot(a)
            return True
    return False


@command("Comment.SetText")
def set_text(doc, page, xref: int, text: str):
    p = doc[page - 1]
    for a in p.annots() or []:
        if a.xref == xref:
            a.set_info(content=text)
            a.update()
            return True
    return False


# ---- appearance -------------------------------------------------------------------------------------
# which properties each kind of comment has; everything also has text and opacity
_A = pymupdf
STYLE_FIELDS = {
    **{t: ("color",) for t in (_A.PDF_ANNOT_HIGHLIGHT, _A.PDF_ANNOT_UNDERLINE, _A.PDF_ANNOT_STRIKE_OUT,
                               _A.PDF_ANNOT_SQUIGGLY, _A.PDF_ANNOT_TEXT, _A.PDF_ANNOT_FILE_ATTACHMENT,
                               _A.PDF_ANNOT_CARET)},
    **{t: ("color", "fill", "width") for t in (_A.PDF_ANNOT_SQUARE, _A.PDF_ANNOT_CIRCLE, _A.PDF_ANNOT_POLYGON)},
    **{t: ("color", "width") for t in (_A.PDF_ANNOT_LINE, _A.PDF_ANNOT_POLY_LINE, _A.PDF_ANNOT_INK)},
    # MuPDF draws a text box border in black whatever is asked, so only its width is offered
    _A.PDF_ANNOT_FREE_TEXT: ("text_color", "fontsize", "fill", "width"),
    _A.PDF_ANNOT_STAMP: (),
}


def _annot(doc, page, xref):
    p = doc[page - 1]
    for a in p.annots() or []:
        if a.xref == xref:
            return p, a
    raise ValueError(f"no comment {xref} on page {page}")


def _font_style(doc, xref) -> tuple[float, tuple]:
    """Font size and text color of a FreeText: its DS style when it has one (rich text), else its DA."""
    size, color = 12.0, (0.0, 0.0, 0.0)
    kind, ds = doc.xref_get_key(xref, "DS")
    if kind == "string":
        for item in ds.split(";"):
            k, _, v = item.partition(":")
            k, v = k.strip(), v.strip()
            if k == "font-size" and v:
                size = float(v.rstrip("pt"))
            elif k == "color" and v.startswith("#") and len(v) == 7:
                color = tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return size, color
    kind, da = doc.xref_get_key(xref, "DA")
    toks = da.split() if kind == "string" else []
    for k, t in enumerate(toks):
        if t == "Tf" and k >= 1:
            size = float(toks[k - 1])
        elif t == "rg" and k >= 3:
            color = tuple(float(x) for x in toks[k - 3:k])
        elif t == "g" and k >= 1:
            color = (float(toks[k - 1]),) * 3
    return size, color


@command("Comment.Style")
def style(doc, page, xref: int) -> dict:
    """The comment's text and appearance, with "fields" naming the properties it has."""
    _p, a = _annot(doc, page, xref)
    t = a.type[0]
    c = a.colors
    content = a.info.get("content", "")
    if not content and doc.xref_get_key(xref, "RC")[0] == "string":     # text boxes from older versions keep only RC
        content = "\n".join(html.unescape(re.sub(r"<[^>]+>", "", m)).replace("\xa0", "")
                            for m in re.findall(r"<p[^>]*>(.*?)</p>", doc.xref_get_key(xref, "RC")[1], re.S))
    out = {"type": a.type[1], "fields": STYLE_FIELDS.get(t, ("color",)), "content": content,
           "rich": doc.xref_get_key(xref, "RC")[0] == "string",
           "color": tuple(c["stroke"]) or None, "fill": tuple(c["fill"]) or None,
           "width": (a.border or {}).get("width", 1) or 0, "opacity": a.opacity if a.opacity >= 0 else 1.0}
    if t == pymupdf.PDF_ANNOT_FREE_TEXT:
        out["fill"] = out["color"]                  # a FreeText's /C is its background
        out["fontsize"], out["text_color"] = _font_style(doc, xref)
    return out


_KEEP = object()


@command("Comment.SetStyle")
def set_style(doc, page, xref: int, text: str | None = None, color=None, fill=_KEEP, width=None, opacity=None,
              fontsize=None, text_color=None):
    """Change any of a comment's text and appearance; arguments left out stay as they are.
    fill=None removes the fill. Colors are RGB tuples of 0..1."""
    _p, a = _annot(doc, page, xref)
    t = a.type[0]
    if text is not None:
        a.set_info(content=text)
        if doc.xref_get_key(xref, "RC")[0] == "string":
            doc.xref_set_key(xref, "RC", pymupdf.get_pdf_str(_rich_body(text)))
    if width is not None and t not in (pymupdf.PDF_ANNOT_HIGHLIGHT, pymupdf.PDF_ANNOT_TEXT, pymupdf.PDF_ANNOT_STAMP):
        a.set_border(width=width)
    if opacity is not None:
        a.set_opacity(opacity)
    if t != pymupdf.PDF_ANNOT_FREE_TEXT:
        if color is not None or fill is not _KEEP:
            a.set_colors(stroke=color if color is not None else a.colors["stroke"],
                         fill=(fill or []) if fill is not _KEEP else a.colors["fill"])
        a.update()
        return True
    size, tcol = _font_style(doc, xref)
    size = fontsize or size
    tcol = text_color if text_color is not None else tcol
    if fill is None:
        doc.xref_set_key(xref, "C", "null")
    if doc.xref_get_key(xref, "RC")[0] == "string":
        doc.xref_set_key(xref, "DS", pymupdf.get_pdf_str(
            "font-family:Helvetica;font-size:%gpt;color:#%02x%02x%02x" % (size, *(round(v * 255) for v in tcol))))
        a = doc[page - 1].load_annot(xref)              # pick up the new style
        a.update(fill_color=fill if fill not in (_KEEP, None) else None)
    else:
        a.update(fontsize=size, text_color=tcol, fill_color=fill if fill not in (_KEEP, None) else None)
    return True


@command("Comment.SetRect")
def set_rect(doc, page, xref: int, rect):
    """Resize a box-shaped comment (rectangle, oval, text box, stamp)."""
    p = doc[page - 1]
    for a in p.annots() or []:
        if a.xref == xref:
            a.set_rect(pymupdf.Rect(rect))
            a.update()
            return True
    return False


@command("Comment.Move")
def move(doc, page, xref: int, dx: float, dy: float):
    p = doc[page - 1]
    for a in p.annots() or []:
        if a.xref == xref:
            a.set_rect(a.rect + (dx, dy, dx, dy))
            a.update()
            return True
    return False
