"""Organize commands (plan phase 1). Each takes/returns pymupdf documents or paths."""
from __future__ import annotations

import pymupdf

from .pages import parse_range
from .registry import command

ARTIFACT_TAG = "pdfdesk-artifact"


@command("Pages.Rotate")
def rotate(doc, angle: int, pages: str | None = None):
    for i in parse_range(pages, doc.page_count):
        p = doc[i]
        p.set_rotation((p.rotation + angle) % 360)


@command("Pages.Delete")
def delete(doc, pages: str):
    doc.delete_pages(parse_range(pages, doc.page_count))


@command("Pages.Reverse")
def reverse(doc, pages: str | None = None):
    idx = parse_range(pages, doc.page_count)
    order = list(range(doc.page_count))
    for dst, src in zip(idx, reversed(idx)):
        order[dst] = src
    doc.select(order)


@command("Pages.Move")
def move(doc, page: int, before: int):
    doc.move_page(page - 1, before - 1 if before <= doc.page_count else -1)


@command("Pages.InsertBlank")
def insert_blank(doc, after: int, width: float = 595, height: float = 842, count: int = 1):
    for k in range(count):
        doc.new_page(pno=after + k, width=width, height=height)


@command("Pages.InsertFile")
def insert_file(doc, path: str, after: int, pages: str | None = None):
    src = pymupdf.open(path)
    for n, i in enumerate(parse_range(pages, src.page_count)):
        doc.insert_pdf(src, from_page=i, to_page=i, start_at=after + n)


@command("Pages.Extract")
def extract(doc, pages: str):
    out = pymupdf.open()
    for i in parse_range(pages, doc.page_count):
        out.insert_pdf(doc, from_page=i, to_page=i)
    return out


@command("Pages.Replace")
def replace(doc, pages: str, src_path: str, src_pages: str | None = None):
    idx = parse_range(pages, doc.page_count)
    src = pymupdf.open(src_path)
    sidx = parse_range(src_pages, src.page_count)
    at = idx[0]
    doc.delete_pages(idx)
    for n, i in enumerate(sidx):
        doc.insert_pdf(src, from_page=i, to_page=i, start_at=at + n)


@command("Pages.Combine")
def combine(paths: list[str], bookmarks: bool = True):
    out = pymupdf.open()
    toc = []
    for path in paths:
        src = pymupdf.open(path)
        start = out.page_count
        out.insert_pdf(src)
        if bookmarks:
            toc.append([1, path.rsplit("/", 1)[-1].rsplit(".", 1)[0], start + 1])
    if toc:
        out.set_toc(out.get_toc() + toc)
    return out


@command("Pages.Split")
def split(doc, every: int | None = None, by_bookmarks: bool = False):
    """Return a list of (name, document)."""
    parts: list[tuple[str, pymupdf.Document]] = []
    if by_bookmarks:
        toc = [t for t in doc.get_toc() if t[0] == 1]
        bounds = [t[2] - 1 for t in toc] + [doc.page_count]
        for k, t in enumerate(toc):
            d = pymupdf.open()
            d.insert_pdf(doc, from_page=bounds[k], to_page=bounds[k + 1] - 1)
            parts.append((t[1], d))
    else:
        every = every or 1
        for s in range(0, doc.page_count, every):
            d = pymupdf.open()
            d.insert_pdf(doc, from_page=s, to_page=min(s + every, doc.page_count) - 1)
            parts.append((f"part{s // every + 1}", d))
    return parts


@command("Pages.Crop")
def crop(doc, pages: str | None = None, margins=None, remove_white: bool = False):
    for i in parse_range(pages, doc.page_count):
        p = doc[i]
        if remove_white:
            bbox = pymupdf.Rect()
            for x0, y0, x1, y1, *_ in p.get_text("blocks"):
                bbox |= pymupdf.Rect(x0, y0, x1, y1)
            for info in p.get_image_info():
                bbox |= pymupdf.Rect(info["bbox"])
            for d in p.get_drawings():
                bbox |= d["rect"]
            if not bbox.is_empty:
                p.set_cropbox(bbox & p.rect)
        elif margins:
            l, t, r, b = margins
            p.set_cropbox(pymupdf.Rect(p.rect.x0 + l, p.rect.y0 + t, p.rect.x1 - r, p.rect.y1 - b))


@command("Pages.Flatten")
def flatten(doc):
    doc.bake(annots=True, widgets=True)


@command("Pages.Labels")
def labels(doc, rules: list[dict]):
    """rules: [{'startpage': 0, 'style': 'r'|'R'|'D'|'a'|'A', 'prefix': '', 'firstpagenum': 1}]"""
    doc.set_page_labels(rules)


# ---- header/footer, watermark, background, Bates --------------------------------

_POS = {"left": 0, "center": 1, "right": 2}


def _expand(text: str, n: int, total: int, bates: dict | None, counter: int) -> str:
    text = text.replace("<<page>>", str(n)).replace("<<total>>", str(total))
    if bates:
        num = bates["start"] + counter * bates.get("increment", 1)
        text = text.replace(
            "<<bates>>", f"{bates.get('prefix', '')}{num:0{bates.get('digits', 6)}d}{bates.get('suffix', '')}")
    return text


@command("Pages.HeaderFooter")
def header_footer(doc, header=("", "", ""), footer=("", "", ""), pages: str | None = None,
                  fontsize: float = 10, margin: float = 36, color=(0, 0, 0), bates: dict | None = None,
                  counter_start: int = 0):
    """header/footer: (left, center, right) with <<page>>, <<total>>, <<bates>> macros.
    Text is placed inside an optional-content group named 'pdfdesk-headerfooter' so it can be removed."""
    ocg = _ocg(doc, ARTIFACT_TAG + "-headerfooter")
    idx = parse_range(pages, doc.page_count)
    for k, i in enumerate(idx):
        p = doc[i]
        r = p.rect
        for row, y in ((header, r.y0 + margin), (footer, r.y1 - margin)):
            for col, text in zip(("left", "center", "right"), row):
                if not text:
                    continue
                s = _expand(text, i + 1, doc.page_count, bates, counter_start + k)
                w = pymupdf.get_text_length(s, "helv", fontsize)
                x = {"left": r.x0 + margin, "center": (r.x0 + r.x1 - w) / 2, "right": r.x1 - margin - w}[col]
                p.insert_text((x, y), s, fontsize=fontsize, fontname="helv", color=color, oc=ocg)
    return counter_start + len(idx)


def _ocg(doc, name: str) -> int:
    for xref, info in doc.get_ocgs().items():
        if info["name"] == name:
            return xref
    return doc.add_ocg(name, on=True)


@command("Pages.RemoveHeaderFooter")
def remove_header_footer(doc):
    _remove_layer_content(doc, ARTIFACT_TAG + "-headerfooter")


@command("Pages.Watermark")
def watermark(doc, text: str, pages: str | None = None, fontsize: float = 60, rotate: float = 45,
              opacity: float = 0.3, color=(0.6, 0.6, 0.6), behind: bool = False):
    ocg = _ocg(doc, ARTIFACT_TAG + "-watermark")
    for i in parse_range(pages, doc.page_count):
        p = doc[i]
        w = pymupdf.get_text_length(text, "helv", fontsize)
        c = p.rect.tl + (p.rect.br - p.rect.tl) / 2
        mat = pymupdf.Matrix(rotate)
        pos = pymupdf.Point(c.x - w / 2, c.y + fontsize / 3)
        p.insert_text(pos, text, fontsize=fontsize, fontname="helv", color=color, fill_opacity=opacity,
                      morph=(c, mat), overlay=not behind, oc=ocg)


@command("Pages.RemoveWatermark")
def remove_watermark(doc):
    _remove_layer_content(doc, ARTIFACT_TAG + "-watermark")


@command("Pages.Background")
def background(doc, color=(1, 1, 0.8), pages: str | None = None):
    ocg = _ocg(doc, ARTIFACT_TAG + "-background")
    for i in parse_range(pages, doc.page_count):
        p = doc[i]
        p.draw_rect(p.rect, color=None, fill=color, overlay=False, oc=ocg)


@command("Pages.RemoveBackground")
def remove_background(doc):
    _remove_layer_content(doc, ARTIFACT_TAG + "-background")


def _remove_layer_content(doc, name: str):
    """Delete marked content belonging to one of our OCGs from every page's content streams."""
    import re
    xrefs = [x for x, i in doc.get_ocgs().items() if i["name"] == name]
    if not xrefs:
        return
    for page in doc:
        props = page.get_oc_items() if hasattr(page, "get_oc_items") else []
        res = doc.xref_get_key(page.xref, "Resources")
        for cx in page.get_contents():
            data = doc.xref_stream(cx)
            for key, xr in _prop_names(doc, page):
                if xr in xrefs:
                    pat = re.compile(rb"/OC\s*/" + key.encode() + rb"\s*BDC.*?EMC", re.S)
                    data = pat.sub(b"", data)
            doc.update_stream(cx, data)
    # drop the OCG from the catalog
    for x in xrefs:
        pass


def _prop_names(doc, page):
    res = doc.xref_get_key(page.xref, "Resources")
    out = []
    if res[0] == "xref":
        rx = int(res[1].split()[0])
    else:
        rx = page.xref
    props = doc.xref_get_key(rx, "Properties")
    if props[0] == "dict":
        import re
        for name, ref in re.findall(r"/(\w+)\s+(\d+)\s+0\s+R", props[1]):
            out.append((name, int(ref)))
    elif props[0] == "xref":
        px = int(props[1].split()[0])
        for k in doc.xref_get_keys(px):
            v = doc.xref_get_key(px, k)
            if v[0] == "xref":
                out.append((k, int(v[1].split()[0])))
    return out
