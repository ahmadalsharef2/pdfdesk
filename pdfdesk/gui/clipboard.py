"""Copy, cut and paste of comments and page objects (Ctrl+C / Ctrl+X / Ctrl+V and the right-click menus).

The selection goes to the system clipboard as a pdfdesk item (JSON under its own MIME type) together with a
plain-text or image rendering for other programs. Pasting takes the pdfdesk item while the clipboard still
holds one, else whatever image or text another program left there. Within its own document an object is
duplicated instruction by instruction; into another document it travels as a snapshot of its page clipped to
its box, so fonts and images come along.
"""
from __future__ import annotations

import base64
import json

import pymupdf
from PySide6.QtCore import QBuffer, QIODevice, QMimeData
from PySide6.QtGui import QGuiApplication, QImage

from ..commands import run
from ..lang import tr
from . import prefs

MIME = "application/x-pdfdesk-item"
OFFSET = 12                  # a copy pasted onto its own page sits this far right and down of the original


# ---- copying -----------------------------------------------------------------------------------------------
def copy_selection(view) -> str | None:
    """Put the view's selected comment or object on the clipboard. Returns a status message, or None when
    nothing is selected."""
    md = QMimeData()
    if view.obj_sel:
        i, n = view.obj_sel
        o = next((o for o in view.page_objects(i) if o.index == n), None)
        if o is None:
            return None
        item = run("Object.Copy", view.doc, i + 1, n)
        payload = {"kind": "object", "view": view.token, "page": i, "index": n, "rect": list(o.rect),
                   "item": _object_to_json(item),
                   "snapshot": base64.b64encode(_page_snapshot(view.doc, i)).decode()}
        data, _ext = run("Object.ExportImage", view.doc, i + 1, n, dpi=200)
        img = QImage.fromData(data)
        if not img.isNull():
            md.setImageData(img)
        if o.kind == "text":
            md.setText(view.doc[i].get_text(clip=o.rect + (-1, -1, 1, 1)).strip())
        label = tr("Object copied")
    elif view.selected:
        i, xref = view.selected
        item = run("Comment.Copy", view.doc, i + 1, xref)
        payload = {"kind": "comment", "view": view.token, "page": i, "rect": list(item["rect"]), "item": item}
        if item["content"]:
            md.setText(item["content"])
        label = tr("Comment copied")
    else:
        return None
    md.setData(MIME, json.dumps(payload).encode())
    QGuiApplication.clipboard().setMimeData(md)
    return label


def _page_snapshot(doc, i: int) -> bytes:
    """A one-page PDF of page i (without comments): how an object travels to another document."""
    tmp = pymupdf.open()
    tmp.insert_pdf(doc, from_page=i, to_page=i, annots=False)
    return tmp.tobytes(garbage=3, deflate=True)


def _object_to_json(item: dict) -> dict:
    return {**item, "content": base64.b64encode(item["content"]).decode(),
            "resources": [[cat, name, val] for (cat, name), val in item["resources"].items()],
            "rect": list(item["rect"]), "matrix": list(item["matrix"])}


def _object_from_json(j: dict) -> dict:
    return {**j, "content": base64.b64decode(j["content"]),
            "resources": {(cat, name): val for cat, name, val in j["resources"]}}


# ---- pasting ------------------------------------------------------------------------------------------------
def _payload() -> dict | None:
    md = QGuiApplication.clipboard().mimeData()
    if md is not None and md.hasFormat(MIME):
        try:
            return json.loads(bytes(md.data(MIME)).decode())
        except ValueError:
            return None
    return None


def describe() -> str | None:
    """What a paste would bring ("Comment", "Object", "Image", "Text"), or None when there is nothing."""
    payload = _payload()
    if payload:
        return payload["kind"].capitalize()
    md = QGuiApplication.clipboard().mimeData()
    if md is None:
        return None
    if md.hasImage():
        return "Image"
    return "Text" if md.text().strip() else None


def paste_action(view, page: int, point=None):
    """What pasting onto a 1-based page means: (label, fn(doc) -> result, select(view, result)). The item's
    top-left goes to point; without one it keeps its place, or sits just below a copy on its own page.
    None when there is nothing to paste."""
    payload = _payload()
    if payload:
        rect = _target_rect(view, page, point, payload)
        same = payload["view"] == view.token
        if payload["kind"] == "comment":
            item = payload["item"]
            if not same and not item["portable"]:
                raise ValueError(tr("A file attachment cannot be pasted into another document"))
            ap = item["ap"] if same else None
            return ("Paste comment", lambda d: run("Comment.Paste", d, page, item["source"], rect, ap=ap),
                    lambda v, xref: _select_comment(v, page, xref))
        if same and _still_there(view, payload):
            item = _object_from_json(payload["item"])
            fn = lambda d: run("Object.Paste", d, page, item, rect)
        else:
            snap = base64.b64decode(payload["snapshot"])
            fn = lambda d: run("Object.PasteFrom", d, page, snap, payload["rect"], rect)
        return "Paste object", fn, lambda v, _r: v.select_last_object(page - 1)
    md = QGuiApplication.clipboard().mimeData()
    if md is None:
        return None
    pt = pymupdf.Point(point) if point is not None else pymupdf.Point(72, 72)
    if md.hasImage():
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        QGuiApplication.clipboard().image().save(buf, "PNG")
        label, fn = image_action(view, page, pt, bytes(buf.data()))
        return label, fn, lambda v, _r: v.select_last_object(page - 1)
    text = md.text().strip()
    if text:
        size = prefs.get_float("text_size/add-text", 10.0)
        return ("Paste text", lambda d: run("Text.Add", d, page, pt, text, fontsize=size),
                lambda v, _r: v.select_last_object(page - 1))
    return None


def image_action(view, page: int, point, data: bytes):
    """(label, fn(doc)) placing image data with its top-left at point, scaled to fit the page."""
    img = QImage.fromData(data)
    if img.isNull():
        raise ValueError(tr("This is not an image Qt can read."))
    w, h = img.width() * 0.75, img.height() * 0.75          # pixels at 96 dpi -> points
    pr = view.doc[page - 1].rect
    k = max(0.05, min(1.0, (pr.width - point.x - 10) / w if w else 1, 300 / max(w, h, 1)))
    rect = pymupdf.Rect(point.x, point.y, point.x + w * k, point.y + h * k)
    return "Add image", lambda d: run("Sign.Image", d, page, rect, data=data)


def _still_there(view, payload) -> bool:
    """Same-document duplication needs the original as it was copied (it may have been cut or undone)."""
    o = next((o for o in view.page_objects(payload["page"]) if o.index == payload["index"]), None)
    return o is not None and all(abs(a - b) < 0.5 for a, b in zip(o.rect, payload["rect"]))


def _target_rect(view, page: int, point, payload) -> pymupdf.Rect:
    r = pymupdf.Rect(payload["rect"])
    if point is not None:
        tl = pymupdf.Point(point)
    elif payload["view"] == view.token and payload["page"] == page - 1:
        tl = r.tl + (OFFSET, OFFSET)
    else:
        tl = r.tl
    p = view.doc[page - 1]
    bounds = (p.rect * p.derotation_matrix).normalize()      # the page in unrotated coordinates
    x = min(max(tl.x, bounds.x0), max(bounds.x0, bounds.x1 - r.width))
    y = min(max(tl.y, bounds.y0), max(bounds.y0, bounds.y1 - r.height))
    return pymupdf.Rect(x, y, x + r.width, y + r.height)


def _select_comment(view, page: int, xref):
    if xref:
        view.selected, view.obj_sel = (page - 1, xref), None
        view.viewport().update()
