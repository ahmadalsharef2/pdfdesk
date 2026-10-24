"""Bookmarks, links and layers."""
from __future__ import annotations

import re

import pymupdf

from .pages import parse_range
from .registry import command


# ---- bookmarks -------------------------------------------------------------------------------------
@command("Bookmarks.List")
def bookmarks(doc) -> list[list]:
    """[[level, title, page], ...] in document order."""
    return doc.get_toc(simple=True)


@command("Bookmarks.Add")
def add_bookmark(doc, title: str, page: int, level: int = 1, index: int | None = None):
    """Insert a bookmark. Without `index` it goes after the last bookmark that points at or before `page`."""
    toc = doc.get_toc(simple=False)
    if index is None:
        index = sum(1 for e in toc if e[2] <= page)
    prev = toc[index - 1][0] if index else 1
    level = max(1, min(level, prev + 1))
    toc.insert(index, [level, title, page])
    doc.set_toc(toc)
    return index


@command("Bookmarks.Rename")
def rename_bookmark(doc, index: int, title: str):
    toc = doc.get_toc(simple=False)
    toc[index][1] = title
    doc.set_toc(toc)


@command("Bookmarks.SetPage")
def set_bookmark_page(doc, index: int, page: int):
    toc = doc.get_toc(simple=False)
    toc[index][2] = page
    if len(toc[index]) > 3:
        toc[index][3] = {"kind": pymupdf.LINK_GOTO, "page": page - 1}
    doc.set_toc(toc)


@command("Bookmarks.Delete")
def delete_bookmark(doc, index: int, children: bool = True):
    """Delete a bookmark; with children=True its sub-bookmarks go too, otherwise they move up a level."""
    toc = doc.get_toc(simple=False)
    lvl = toc[index][0]
    end = index + 1
    while end < len(toc) and toc[end][0] > lvl:
        end += 1
    if children:
        del toc[index:end]
    else:
        for e in toc[index + 1:end]:
            e[0] -= 1
        del toc[index]
    doc.set_toc(toc)


@command("Bookmarks.Indent")
def indent_bookmark(doc, index: int, delta: int):
    """Demote (delta=+1) or promote (delta=-1) a bookmark and its children."""
    toc = doc.get_toc(simple=False)
    lvl = toc[index][0]
    prev = toc[index - 1][0] if index else 0
    if not (1 <= lvl + delta <= prev + 1):
        raise ValueError("cannot move the bookmark to that level")
    end = index + 1
    while end < len(toc) and toc[end][0] > lvl:
        end += 1
    for e in toc[index:end]:
        e[0] += delta
    doc.set_toc(toc)


@command("Bookmarks.Clear")
def clear_bookmarks(doc):
    doc.set_toc([])


@command("Bookmarks.FromHeadings")
def bookmarks_from_headings(doc, levels: int = 3, min_ratio: float = 1.15, replace: bool = True) -> int:
    """Build bookmarks from text that is larger than the body text (Foxit's "Add bookmarks from structure"
    for untagged files). Font sizes larger than body * min_ratio are ranked into up to `levels` levels."""
    from collections import Counter
    sizes = Counter()
    lines = []
    for page in doc:
        fields = [w.rect for w in page.widgets()]
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                text = "".join(s["text"] for s in ln["spans"]).strip()
                if not text or any(pymupdf.Rect(ln["bbox"]).intersects(r) for r in fields):
                    continue  # form field values are not headings
                size = round(max(s["size"] for s in ln["spans"]), 1)
                sizes[size] += len(text)
                lines.append((page.number + 1, ln["bbox"][1], size, text))
    if not sizes:
        return 0
    body = sizes.most_common(1)[0][0]
    heads = sorted({s for s in sizes if s >= body * min_ratio}, reverse=True)[:levels]
    rank = {s: k + 1 for k, s in enumerate(heads)}
    toc, last = [], None
    for page, _, size, text in lines:
        if size not in rank or len(text) > 120 or re.fullmatch(r"[\d\W]+", text):
            continue
        lvl = rank[size]
        if last and last[0] == lvl and last[2] == page and toc:  # heading wrapped onto a second line
            toc[-1][1] += " " + text
            continue
        lvl = min(lvl, (toc[-1][0] + 1) if toc else 1)
        toc.append([lvl, text, page])
        last = (lvl, text, page)
    if not replace:
        toc = sorted(doc.get_toc(simple=True) + toc, key=lambda e: e[2])
    doc.set_toc(toc)
    return len(toc)


# ---- links ---------------------------------------------------------------------------------------------
def _pdf_string(doc, xref: int, key: str) -> str | None:
    t, v = doc.xref_get_key(xref, key)
    return v if t == "string" else None


def _page_links(doc, i: int) -> list[dict]:
    """Links read from the page's /Annots. Page.get_links() on a page object that was loaded before a link was
    inserted misses the new link (PyMuPDF 2.0), and reload_page fails while the viewer holds the page."""
    page = doc[i]
    out = []
    for x in [int(n) for n in re.findall(r"(\d+) 0 R", doc.xref_get_key(page.xref, "Annots")[1])]:
        if doc.xref_get_key(x, "Subtype")[1] != "/Link":
            continue
        r = pymupdf.Rect([float(v) for v in doc.xref_get_key(x, "Rect")[1].strip("[] ").split()])
        r = (r * page.transformation_matrix).normalize()
        e = {"page": i + 1, "rect": tuple(r), "uri": _pdf_string(doc, x, "A/URI"), "target": None,
             "file": _pdf_string(doc, x, "A/F"), "xref": x}
        dest = doc.xref_get_key(x, "Dest")
        if dest[0] == "null":
            dest = doc.xref_get_key(x, "A/D")
        m = re.match(r"\[\s*(\d+) 0 R", dest[1] or "")
        if m:
            e["target"] = next((p.number + 1 for p in doc if p.xref == int(m.group(1))), None)
        elif e["file"]:
            m = re.match(r"\[\s*(\d+)", dest[1] or "")
            e["target"] = int(m.group(1)) + 1 if m else 1
        out.append(e)
    return out


@command("Links.List")
def links(doc, pages: str | None = None) -> list[dict]:
    return [e for i in parse_range(pages, doc.page_count) for e in _page_links(doc, i)]


@command("Links.AddUrl")
def add_url_link(doc, page: int, rect, url: str):
    doc[page - 1].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(rect), "uri": url})


@command("Links.AddPage")
def add_page_link(doc, page: int, rect, target: int, zoom: float = 0):
    doc[page - 1].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(rect), "page": target - 1,
                               "to": pymupdf.Point(0, 0), "zoom": zoom})


@command("Links.AddFile")
def add_file_link(doc, page: int, rect, path: str, target: int = 1):
    doc[page - 1].insert_link({"kind": pymupdf.LINK_GOTOR, "from": pymupdf.Rect(rect), "file": path,
                               "page": target - 1, "to": pymupdf.Point(0, 0)})


@command("Links.Remove")
def remove_links(doc, pages: str | None = None, point=None, page: int | None = None) -> int:
    """Remove every link on the pages, or only the link under `point` on `page`."""
    n = 0
    idx = [page - 1] if page else parse_range(pages, doc.page_count)
    for i in idx:
        pg = doc[i]
        for e in _page_links(doc, i):
            if point is None or pymupdf.Rect(e["rect"]).contains(pymupdf.Point(point)):
                pg.delete_link({"xref": e["xref"], "kind": pymupdf.LINK_URI if e["uri"] else pymupdf.LINK_GOTO,
                                "from": pymupdf.Rect(e["rect"])})
                n += 1
    return n


URL_RX = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+|[\w.+-]+@[\w-]+\.[\w.-]+")


@command("Links.Detect")
def detect_links(doc, pages: str | None = None) -> int:
    """Foxit's "Create links from URLs": web addresses and e-mail addresses in the text become links."""
    n = 0
    for i in parse_range(pages, doc.page_count):
        pg = doc[i]
        have = [pymupdf.Rect(e["rect"]) for e in _page_links(doc, i)] + [w.rect for w in pg.widgets()]
        words = pg.get_text("words")
        for w in words:
            for m in URL_RX.finditer(w[4]):
                s = m.group(0).rstrip(".,;:")
                if m.start() > 0 or len(s) < 5:
                    continue
                r = pymupdf.Rect(w[:4])
                if any(r.intersects(h) for h in have):
                    continue
                uri = s if "://" in s else (f"mailto:{s}" if "@" in s and not s.startswith("www.") else f"https://{s}")
                pg.insert_link({"kind": pymupdf.LINK_URI, "from": r, "uri": uri})
                have.append(r)
                n += 1
    return n


# ---- layers --------------------------------------------------------------------------------------------
@command("Layers.List")
def layers(doc) -> list[dict]:
    off = set(doc.get_layer().get("off") or [])
    return [{"xref": x, "name": v["name"], "on": x not in off, "intent": v.get("intent")}
            for x, v in doc.get_ocgs().items()]


@command("Layers.SetVisible")
def set_layer_visible(doc, xref: int, visible: bool):
    ocgs = doc.get_ocgs()
    off_now = set(doc.get_layer().get("off") or [])
    on = [x for x in ocgs if (x not in off_now if x != xref else visible)]
    off = [x for x in ocgs if x not in on]
    doc.set_layer(-1, on=on, off=off)


@command("Layers.Add")
def add_layer(doc, name: str, on: bool = True) -> int:
    return doc.add_ocg(name, on=on)

