"""Edit Object: find, move, resize and delete placed objects (images and form XObjects) in page content.

An object is one ``Do`` operator in the page's own content streams. Its box comes from the current
transformation matrix at that point. Moving or resizing wraps the ``Do`` in ``q <matrix> cm ... Q``, so
nothing else on the page changes. Objects are identified by the position of their ``Do`` among all ``Do``
operators of the page, which stays stable across these edits.
"""
from __future__ import annotations

from dataclasses import dataclass

import pikepdf
import pymupdf

from .registry import command


@dataclass
class PageObject:
    index: int              # n-th Do operator on the page
    kind: str               # "image" or "form"
    name: str               # resource name, e.g. "Im0" or "fzFrm0"
    rect: pymupdf.Rect      # unrotated page coordinates (same space as annotations)


def _M(m) -> pymupdf.Matrix:
    return pymupdf.Matrix(*[float(x) for x in m])


def _content(doc, page: pymupdf.Page) -> bytes:
    return b"\n".join(doc.xref_stream(x) or b"" for x in page.get_contents())


def _parse(data: bytes):
    pdf = pikepdf.new()
    return pikepdf.parse_content_stream(pikepdf.Stream(pdf, data))


def _xobjects(doc, page: pymupdf.Page) -> dict[str, tuple[str, pymupdf.Rect]]:
    """Resource name -> (kind, box in the object's own space)."""
    out = {}
    for img in page.get_images(full=True):
        out[img[7]] = ("image", pymupdf.Rect(0, 0, 1, 1))
    for xref, name, _invoker, _bbox in page.get_xobjects():
        t, bbox = doc.xref_get_key(xref, "BBox")
        if t != "array":
            continue
        r = pymupdf.Rect([float(v) for v in bbox.strip("[]").split()])
        t, m = doc.xref_get_key(xref, "Matrix")
        if t == "array":
            r = r * pymupdf.Matrix(*[float(v) for v in m.strip("[]").split()])
        out[name] = ("form", r)
    return out


def _walk(doc, page: pymupdf.Page):
    """Yield (instruction position, Do index, name, CTM in PDF space) for every Do in the page content."""
    ops = _parse(_content(doc, page))
    ctm, stack, n = pymupdf.Matrix(1, 1), [], 0
    for pos, ins in enumerate(ops):
        op = str(ins.operator)
        if op == "q":
            stack.append(ctm)
        elif op == "Q":
            ctm = stack.pop() if stack else pymupdf.Matrix(1, 1)
        elif op == "cm":
            ctm = _M(ins.operands) * ctm
        elif op == "Do":
            yield ops, pos, n, str(ins.operands[0]).lstrip("/"), ctm
            n += 1


def _to_page(page: pymupdf.Page) -> pymupdf.Matrix:
    """PDF user space -> unrotated page coordinates."""
    return page.transformation_matrix          # MuPDF's matrix ignores /Rotate, as our coordinates do


@command("Object.List")
def list_objects(doc, page: int) -> list[PageObject]:
    p = doc[page - 1]
    xo = _xobjects(doc, p)
    tp = _to_page(p)
    out = []
    for _ops, _pos, n, name, ctm in _walk(doc, p):
        if name in xo:
            kind, box = xo[name]
            r = (box * ctm * tp).normalize()
            if not r.is_empty:
                out.append(PageObject(n, kind, name, r))
    return out


@command("Object.At")
def object_at(doc, page: int, point) -> PageObject | None:
    pt = pymupdf.Point(point)
    hits = [o for o in list_objects(doc, page) if (o.rect + (-2, -2, 2, 2)).contains(pt)]
    return min(hits, key=lambda o: o.rect.get_area()) if hits else None


def _rewrite(doc, page: pymupdf.Page, index: int, fn):
    """fn(ops, pos, ctm) edits the instruction list in place for Do number index; then write it back."""
    for ops, pos, n, _name, ctm in _walk(doc, page):
        if n == index:
            fn(ops, pos, ctm)
            data = pikepdf.unparse_content_stream(ops)
            xrefs = page.get_contents()
            doc.update_stream(xrefs[0], data)
            for x in xrefs[1:]:
                doc.update_stream(x, b"")
            return True
    raise IndexError(f"no object {index} on page {page.number + 1}")


@command("Object.Transform")
def transform(doc, page: int, index: int, new_rect):
    """Move/resize object number index so its box becomes new_rect (unrotated page coordinates)."""
    p = doc[page - 1]
    old = next(o.rect for o in list_objects(doc, page) if o.index == index)
    new = pymupdf.Rect(new_rect)
    sx, sy = new.width / max(old.width, 1e-6), new.height / max(old.height, 1e-6)
    # page-space change: scale about the old corner, then move to the new corner
    a_page = pymupdf.Matrix(1, 0, 0, 1, -old.x0, -old.y0) * pymupdf.Matrix(sx, sy) * \
        pymupdf.Matrix(1, 0, 0, 1, new.x0, new.y0)
    tp = _to_page(p)
    a_pdf = tp * a_page * ~tp

    def edit(ops, pos, ctm):
        n = ctm * a_pdf * ~ctm          # applied before the existing CTM: n x ctm = ctm x a_pdf
        do = ops[pos]
        ops[pos:pos + 1] = [pikepdf.ContentStreamInstruction([], pikepdf.Operator("q")),
                            pikepdf.ContentStreamInstruction([n.a, n.b, n.c, n.d, n.e, n.f], pikepdf.Operator("cm")),
                            do,
                            pikepdf.ContentStreamInstruction([], pikepdf.Operator("Q"))]
    return _rewrite(doc, p, index, edit)


@command("Object.Delete")
def delete(doc, page: int, index: int):
    def edit(ops, pos, _ctm):
        del ops[pos]
    return _rewrite(doc, doc[page - 1], index, edit)
