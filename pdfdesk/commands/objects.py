"""Edit Object: find, move, resize and delete placed objects in page content.

An object is a run of instructions in the page's own content streams:

- ``image`` / ``form``: one ``Do`` operator, or one inline image;
- ``text``: one ``BT ... ET`` block;
- ``path``: the path construction operators (``m l c v y re h``) and the painting operator that ends them.

Boxes come from the current transformation matrix: for Do and paths directly, for text through MuPDF's text
trace (every span starts at the origin of some show operator, so spans are matched back to their block).
Moving or resizing wraps the run in ``q <matrix> cm ... Q``, so nothing else on the page changes. Objects are
identified by their position among all objects of the page, which stays stable across these edits.
"""
from __future__ import annotations

from dataclasses import dataclass

import pikepdf
import pymupdf

from .registry import command

PATH_OPS = {"m", "l", "c", "v", "y", "re", "h"}
PAINT_OPS = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*"}
STROKE_OPS = {"S", "s", "B", "B*", "b", "b*"}
SHOW_OPS = {"Tj", "TJ", "'", '"'}
# operators inside BT ... ET whose effect outlives the block; re-emitted after a Q so later content is unchanged
STATE_OPS = {"Tf", "Tc", "Tw", "Tz", "TL", "Ts", "Tr", "rg", "RG", "g", "G", "k", "K", "cs", "CS", "sc", "SC",
             "scn", "SCN", "gs", "w", "J", "j", "M", "d", "ri", "i"}


@dataclass
class PageObject:
    index: int              # n-th object on the page
    kind: str               # "image", "form", "text" or "path"
    name: str               # resource name ("Im0", "fzFrm0"), or the text / paint operator
    rect: pymupdf.Rect      # unrotated page coordinates (same space as annotations)


@dataclass
class _Run:
    start: int              # first instruction
    end: int                # last instruction (inclusive)
    kind: str
    name: str
    ctm: pymupdf.Matrix
    box: pymupdf.Rect | None = None          # path: box in page coordinates
    starts: tuple = ()                       # text: origins of show operators in page coordinates


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


def _to_page(page: pymupdf.Page) -> pymupdf.Matrix:
    """PDF user space -> unrotated page coordinates."""
    return page.transformation_matrix          # MuPDF's matrix ignores /Rotate, as our coordinates do


def _walk(doc, page: pymupdf.Page):
    """Parse the page content; return (instructions, object runs in content order)."""
    ops = _parse(_content(doc, page))
    tp = _to_page(page)
    ctm, stack, runs = pymupdf.Matrix(1, 1), [], []
    lw, path_start, pts = 1.0, None, []
    bt, tm, tlm, tl, size, hscale, starts = None, None, None, 0.0, 0.0, 1.0, []
    for pos, ins in enumerate(ops):
        op = str(ins.operator)
        a = ins.operands
        if op in PATH_OPS:
            if path_start is None:
                path_start, pts = pos, []
            v = [float(x) for x in a]
            if op == "re":
                x, y, w, h = v
                pts += [pymupdf.Point(x, y), pymupdf.Point(x + w, y + h), pymupdf.Point(x + w, y),
                        pymupdf.Point(x, y + h)]
            else:
                pts += [pymupdf.Point(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
            continue
        if op in PAINT_OPS and path_start is not None and pts:
            m = ctm * tp
            r = pymupdf.Rect(pts[0] * m, pts[0] * m)
            for q in pts[1:]:
                r |= q * m
            if op in STROKE_OPS:
                pad = lw * max(abs(m.a), abs(m.b), abs(m.c), abs(m.d)) / 2
                r = r + (-pad, -pad, pad, pad)
            runs.append(_Run(path_start, pos, "path", op, ctm, box=r))
            path_start = None
            continue
        path_start = None                       # n, W, or anything else ends the path without painting
        if op == "q":
            stack.append((ctm, lw))
        elif op == "Q":
            ctm, lw = stack.pop() if stack else (pymupdf.Matrix(1, 1), 1.0)
        elif op == "cm":
            ctm = _M(a) * ctm
        elif op == "w":
            lw = float(a[0])
        elif op == "Tf":
            size = float(a[1])
        elif op == "Tz":
            hscale = float(a[0]) / 100
        elif op == "TL":
            tl = float(a[0])
        elif op == "BT":
            bt, tm, tlm, starts = pos, pymupdf.Matrix(1, 1), pymupdf.Matrix(1, 1), []
        elif op == "ET" and bt is not None:
            runs.append(_Run(bt, pos, "text", "BT", ctm, starts=tuple(starts)))
            bt = None
        elif bt is not None and op in ("Td", "TD"):
            tx, ty = float(a[0]), float(a[1])
            if op == "TD":
                tl = -ty
            tlm = pymupdf.Matrix(1, 0, 0, 1, tx, ty) * tlm
            tm = pymupdf.Matrix(tlm)
        elif bt is not None and op == "Tm":
            tlm = _M(a)
            tm = pymupdf.Matrix(tlm)
        elif bt is not None and op == "T*":
            tlm = pymupdf.Matrix(1, 0, 0, 1, 0, -tl) * tlm
            tm = pymupdf.Matrix(tlm)
        elif bt is not None and op in SHOW_OPS:
            if op in ("'", '"'):
                tlm = pymupdf.Matrix(1, 0, 0, 1, 0, -tl) * tlm
                tm = pymupdf.Matrix(tlm)
            shift = 0.0
            if op == "TJ":
                for el in a[0]:                 # leading kerning numbers move the first glyph
                    if isinstance(el, pikepdf.String):
                        break
                    shift -= float(el) / 1000 * size * hscale
            starts.append(pymupdf.Point(shift, 0) * tm * ctm * tp)
        elif op == "Do":
            runs.append(_Run(pos, pos, "xobject", str(a[0]).lstrip("/"), ctm))
        elif op == "INLINE IMAGE":
            runs.append(_Run(pos, pos, "image", "inline", ctm))
    return ops, runs


def _text_boxes(page: pymupdf.Page, runs: list[_Run]) -> dict[int, pymupdf.Rect]:
    """Run number -> box of its text, by matching each traced span to the show operator it starts at."""
    targets = [(k, p) for k, r in enumerate(runs) if r.kind == "text" for p in r.starts]
    boxes: dict[int, pymupdf.Rect] = {}
    if not targets:
        return boxes
    for span in page.get_texttrace():
        if not span["chars"]:
            continue
        o = pymupdf.Point(span["chars"][0][2])
        k, p = min(targets, key=lambda t: abs(t[1].x - o.x) + abs(t[1].y - o.y))
        if abs(p.x - o.x) + abs(p.y - o.y) > max(3.0, span["size"] * 0.6):
            continue                            # text of a form XObject or an annotation, not ours
        r = pymupdf.Rect(span["bbox"])
        boxes[k] = boxes[k] | r if k in boxes else r
    return boxes


def _objects(doc, page: pymupdf.Page):
    """(instructions, [(PageObject, run)]) for every object on the page."""
    ops, runs = _walk(doc, page)
    xo = _xobjects(doc, page)
    tp = _to_page(page)
    text = _text_boxes(page, runs)
    out = []
    for k, r in enumerate(runs):
        if r.kind == "xobject":
            if r.name not in xo:
                continue
            kind, box = xo[r.name]
            rect = (box * r.ctm * tp).normalize()
        elif r.kind == "image":
            kind, rect = "image", (pymupdf.Rect(0, 0, 1, 1) * r.ctm * tp).normalize()
        elif r.kind == "text":
            kind, rect = "text", text.get(k)
            if rect is None:
                continue
        else:
            kind, rect = "path", r.box
        if rect.is_empty and kind != "path" or rect.width <= 0 and rect.height <= 0:
            continue
        out.append((PageObject(len(out), kind, r.name, rect), r))
    return ops, out


@command("Object.List")
def list_objects(doc, page: int, kinds=None) -> list[PageObject]:
    """Objects on a 1-based page; kinds limits them, e.g. {"image", "text"}."""
    _ops, objs = _objects(doc, doc[page - 1])
    return [o for o, _r in objs if kinds is None or o.kind in kinds]


@command("Object.At")
def object_at(doc, page: int, point, kinds=None) -> PageObject | None:
    pt = pymupdf.Point(point)
    hits = [o for o in list_objects(doc, page, kinds) if (o.rect + (-2, -2, 2, 2)).contains(pt)]
    return min(hits, key=lambda o: o.rect.get_area()) if hits else None


def _rewrite(doc, page: pymupdf.Page, index: int, fn):
    """fn(ops, run) edits the instruction list in place for object number index; then write it back."""
    ops, objs = _objects(doc, page)
    run = next((r for o, r in objs if o.index == index), None)
    if run is None:
        raise IndexError(f"no object {index} on page {page.number + 1}")
    fn(ops, run)
    data = pikepdf.unparse_content_stream(ops)
    xrefs = page.get_contents()
    doc.update_stream(xrefs[0], data)
    for x in xrefs[1:]:
        doc.update_stream(x, b"")
    return True


def _state_after(ops, run) -> list:
    """The state operators of a text block, to repeat after it is wrapped in q ... Q or removed."""
    if run.kind != "text":
        return []
    return [ins for ins in ops[run.start:run.end + 1] if str(ins.operator) in STATE_OPS]


def _ins(op, operands=()):
    return pikepdf.ContentStreamInstruction(list(operands), pikepdf.Operator(op))


@command("Object.Transform")
def transform(doc, page: int, index: int, new_rect):
    """Move/resize object number index so its box becomes new_rect (unrotated page coordinates)."""
    p = doc[page - 1]
    old = next(o.rect for o in list_objects(doc, page) if o.index == index)
    new = pymupdf.Rect(new_rect)
    sx = new.width / old.width if old.width > 1e-6 else 1
    sy = new.height / old.height if old.height > 1e-6 else 1
    # page-space change: scale about the old corner, then move to the new corner
    a_page = pymupdf.Matrix(1, 0, 0, 1, -old.x0, -old.y0) * pymupdf.Matrix(sx, sy) * \
        pymupdf.Matrix(1, 0, 0, 1, new.x0, new.y0)
    tp = _to_page(p)
    a_pdf = tp * a_page * ~tp

    def edit(ops, run):
        n = run.ctm * a_pdf * ~run.ctm          # applied before the existing CTM: n x ctm = ctm x a_pdf
        body = list(ops[run.start:run.end + 1])
        ops[run.start:run.end + 1] = [_ins("q"), _ins("cm", [n.a, n.b, n.c, n.d, n.e, n.f]), *body, _ins("Q"),
                                      *_state_after(ops, run)]
    return _rewrite(doc, p, index, edit)


@command("Object.Delete")
def delete(doc, page: int, index: int):
    def edit(ops, run):
        ops[run.start:run.end + 1] = _state_after(ops, run)
    return _rewrite(doc, doc[page - 1], index, edit)
