"""Compare two PDFs (plan phase 4): word-stream diff over the whole document + image hash diff."""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field

import pymupdf

from .registry import command

COLORS = {"replace": (1, 0.6, 0), "insert": (0.2, 0.7, 0.2), "delete": (0.9, 0.1, 0.1), "image": (0.2, 0.4, 0.9)}


@dataclass
class Change:
    kind: str                      # replace | insert | delete | image
    old_page: int | None = None
    new_page: int | None = None
    old_rects: list = field(default_factory=list)
    new_rects: list = field(default_factory=list)
    old_text: str = ""
    new_text: str = ""


def _words(doc):
    out = []
    for pno, p in enumerate(doc):
        for x0, y0, x1, y1, w, *_ in p.get_text("words"):
            out.append((pno, pymupdf.Rect(x0, y0, x1, y1), w))
    return out


def _group(ws):
    """Group consecutive words of one page into per-page (page, [rects], text)."""
    by: dict[int, list] = {}
    for pno, r, w in ws:
        by.setdefault(pno, []).append((r, w))
    return [(p, [r for r, _ in v], " ".join(w for _, w in v)) for p, v in by.items()]


def _image_sigs(doc):
    sigs = []
    for pno, p in enumerate(doc):
        for info in p.get_image_info(xrefs=True):
            x = info.get("xref")
            h = hashlib.sha1(doc.extract_image(x)["image"]).hexdigest() if x else None
            sigs.append((pno, pymupdf.Rect(info["bbox"]), h))
    return sigs


def diff(old: pymupdf.Document, new: pymupdf.Document) -> list[Change]:
    a, b = _words(old), _words(new)
    sm = difflib.SequenceMatcher(None, [w for *_, w in a], [w for *_, w in b], autojunk=False)
    changes: list[Change] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        old_g, new_g = _group(a[i1:i2]), _group(b[j1:j2])
        kind = {"replace": "replace", "insert": "insert", "delete": "delete"}[op]
        c = Change(kind, old_g[0][0] if old_g else None, new_g[0][0] if new_g else None,
                   [r for g in old_g for r in g[1]], [r for g in new_g for r in g[1]],
                   " ".join(g[2] for g in old_g), " ".join(g[2] for g in new_g))
        changes.append(c)
    # images: match by hash; same position + different hash => replaced
    ia, ib = _image_sigs(old), _image_sigs(new)
    for pno, r, h in ia:
        match = [x for x in ib if x[0] == pno and abs(x[1].x0 - r.x0) < 20 and abs(x[1].y0 - r.y0) < 20]
        if match and all(m[2] != h for m in match):
            changes.append(Change("image", pno, pno, [r], [match[0][1]]))
    return changes


def summary(changes: list[Change]) -> dict[str, int]:
    s = {k: 0 for k in COLORS}
    for c in changes:
        s[c.kind] += 1
    return s


@command("Compare.Run")
def compare(old: pymupdf.Document, new: pymupdf.Document, opacity: float = 0.35):
    """Return (result_document, changes). Page 1 = summary; then side-by-side pages with markup annotations."""
    changes = diff(old, new)
    out = pymupdf.open()
    sp = out.new_page(width=595, height=842)
    s = summary(changes)
    sp.insert_text((50, 70), "Comparison result", fontsize=20)
    sp.insert_text((50, 100), f"Old: {old.name or 'old'}  ({old.page_count} pages)", fontsize=10)
    sp.insert_text((50, 114), f"New: {new.name or 'new'}  ({new.page_count} pages)", fontsize=10)
    y = 150
    for kind, n in s.items():
        sp.draw_rect(pymupdf.Rect(50, y - 9, 62, y + 3), color=COLORS[kind], fill=COLORS[kind])
        sp.insert_text((70, y), f"{kind.capitalize()}: {n}", fontsize=11)
        y += 20
    ow, oh = old[0].rect.width, old[0].rect.height
    n = max(old.page_count, new.page_count)
    for i in range(n):
        pg = out.new_page(width=ow * 2 + 10, height=oh)
        if i < old.page_count:
            pg.show_pdf_page(pymupdf.Rect(0, 0, ow, oh), old, i)
        if i < new.page_count:
            pg.show_pdf_page(pymupdf.Rect(ow + 10, 0, ow * 2 + 10, oh), new, i)
        for c in changes:
            for side, page, rects, dx in (("old", c.old_page, c.old_rects, 0), ("new", c.new_page, c.new_rects, ow + 10)):
                if page != i:
                    continue
                for r in rects:
                    a = pg.add_rect_annot(pymupdf.Rect(r.x0 + dx, r.y0, r.x1 + dx, r.y1))
                    a.set_colors(stroke=COLORS[c.kind], fill=COLORS[c.kind])
                    a.set_opacity(opacity)
                    a.set_info(content=f"{c.kind}: {c.old_text!r} -> {c.new_text!r}", title="pdfdesk compare")
                    a.update()
    return out, changes
