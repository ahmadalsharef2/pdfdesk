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

from contextlib import contextmanager
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
# state operators that replace each other, so only the last of a group is repeated when a copy is made
_STATE_GROUP = {**{o: "fill" for o in ("rg", "g", "k", "sc", "scn")},
                **{o: "stroke" for o in ("RG", "G", "K", "SC", "SCN")}}
# operator -> (resource category, operand position) of the named resource it uses
RESOURCE_OPS = {"Do": ("XObject", 0), "Tf": ("Font", 0), "gs": ("ExtGState", 0), "cs": ("ColorSpace", 0),
                "CS": ("ColorSpace", 0), "scn": ("Pattern", -1), "SCN": ("Pattern", -1), "sh": ("Shading", 0),
                "BDC": ("Properties", 1)}
MARK = "/PdfDesk"                     # marked-content tag around content pdfdesk added to a page


@dataclass
class PageObject:
    index: int              # n-th object on the page
    kind: str               # "image", "form", "text" or "path"
    name: str               # resource name ("Im0", "fzFrm0"), or the text / paint operator
    rect: pymupdf.Rect      # unrotated page coordinates (same space as annotations)
    added: bool = False     # placed by pdfdesk (inside a /PdfDesk marked-content sequence)
    size: float = 0.0       # text (also text inside a form): its largest font size, else 0


@dataclass
class _Run:
    start: int              # first instruction
    end: int                # last instruction (inclusive)
    kind: str
    name: str
    ctm: pymupdf.Matrix
    box: pymupdf.Rect | None = None          # path: box in page coordinates
    starts: tuple = ()                       # text: origins of show operators in page coordinates
    state: tuple = ()                        # graphics-state instructions in effect when the run starts
    added: bool = False


def _M(m) -> pymupdf.Matrix:
    return pymupdf.Matrix(*[float(x) for x in m])


def _content(doc, page: pymupdf.Page) -> bytes:
    return b"\n".join(doc.xref_stream(x) or b"" for x in page.get_contents())


def _parse(data: bytes):
    pdf = pikepdf.new()
    return pikepdf.parse_content_stream(pikepdf.Stream(pdf, data))


def _resource(doc, page: pymupdf.Page, path: str):
    """xref_get_key of the page's Resources/<path>, also when the resources are inherited."""
    x = page.xref
    while x:
        kind, val = doc.xref_get_key(x, "Resources")
        if kind not in ("null", None):
            return doc.xref_get_key(x, "Resources/" + path)
        kind, val = doc.xref_get_key(x, "Parent")
        x = int(val.split()[0]) if kind == "xref" else 0
    return "null", "null"


def _is_page_resource(doc, page: pymupdf.Page, cat: str, name: str, xref: int) -> bool:
    """get_images and get_xobjects also list what nested forms use; only the page's own names are drawn by
    the page content."""
    kind, val = _resource(doc, page, f"{cat}/{name}")
    return kind == "xref" and int(val.split()[0]) == xref


def _xobjects(doc, page: pymupdf.Page) -> dict[str, tuple[str, pymupdf.Rect]]:
    """Resource name -> (kind, box in the object's own space)."""
    out = {}
    for img in page.get_images(full=True):
        if _is_page_resource(doc, page, "XObject", img[7], img[0]):
            out[img[7]] = ("image", pymupdf.Rect(0, 0, 1, 1))
    for xref, name, _invoker, _bbox in page.get_xobjects():
        if not _is_page_resource(doc, page, "XObject", name, xref):
            continue
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
    state: list = []                        # STATE_OPS instructions since the last q (restored by Q)
    marks: list[bool] = []                  # open marked-content sequences: True when ours
    for pos, ins in enumerate(ops):
        op = str(ins.operator)
        a = ins.operands
        if op in STATE_OPS and bt is None:
            state.append(ins)
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
            runs.append(_Run(path_start, pos, "path", op, ctm, box=r, state=_last_state(state), added=any(marks)))
            path_start = None
            continue
        path_start = None                       # n, W, or anything else ends the path without painting
        if op == "q":
            stack.append((ctm, lw, list(state)))
        elif op == "Q":
            ctm, lw, state = stack.pop() if stack else (pymupdf.Matrix(1, 1), 1.0, [])
        elif op in ("BMC", "BDC"):
            marks.append(bool(a) and str(a[0]) == MARK)
        elif op == "EMC":
            if marks:
                marks.pop()
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
            runs.append(_Run(bt, pos, "text", "BT", ctm, starts=tuple(starts), state=_last_state(state),
                             added=any(marks)))
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
            runs.append(_Run(pos, pos, "xobject", str(a[0]).lstrip("/"), ctm, state=_last_state(state),
                             added=any(marks)))
        elif op == "INLINE IMAGE":
            runs.append(_Run(pos, pos, "image", "inline", ctm, state=_last_state(state), added=any(marks)))
    return ops, runs


def _last_state(state: list) -> tuple:
    """The instructions that still matter: the last of each operator (or color group), in order."""
    last = {}
    for k, ins in enumerate(state):
        op = str(ins.operator)
        last[_STATE_GROUP.get(op, op)] = k
    return tuple(state[k] for k in sorted(last.values()))


def _text_boxes(page: pymupdf.Page, runs: list[_Run]) -> tuple[dict[int, pymupdf.Rect], dict[int, float]]:
    """Run number -> box of its text, by matching each traced span to the show operator it starts at;
    and run number -> its largest font size."""
    targets = [(k, p) for k, r in enumerate(runs) if r.kind == "text" for p in r.starts]
    boxes: dict[int, pymupdf.Rect] = {}
    sizes: dict[int, float] = {}
    if not targets:
        return boxes, sizes
    for span in page.get_texttrace():
        if not span["chars"]:
            continue
        o = pymupdf.Point(span["chars"][0][2])
        k, p = min(targets, key=lambda t: abs(t[1].x - o.x) + abs(t[1].y - o.y))
        if abs(p.x - o.x) + abs(p.y - o.y) > max(3.0, span["size"] * 0.6):
            continue                            # text of a form XObject or an annotation, not ours
        r = pymupdf.Rect(span["bbox"])
        boxes[k] = boxes[k] | r if k in boxes else r
        sizes[k] = max(sizes.get(k, 0.0), float(span["size"]))
    return boxes, sizes


def _form_text_size(rect: pymupdf.Rect, spans: list) -> float:
    """Largest font size of the page text inside a form's box (text added with Add Text lives in a form)."""
    return max((s for r, s in spans if rect.contains(r.tl + (r.br - r.tl) / 2)), default=0.0)


def _objects(doc, page: pymupdf.Page):
    """(instructions, [(PageObject, run)]) for every object on the page."""
    ops, runs = _walk(doc, page)
    xo = _xobjects(doc, page)
    tp = _to_page(page)
    text, sizes = _text_boxes(page, runs)
    spans = None
    out = []
    for k, r in enumerate(runs):
        size = 0.0
        if r.kind == "xobject":
            if r.name not in xo:
                continue
            kind, box = xo[r.name]
            rect = (box * r.ctm * tp).normalize()
            if kind == "form":
                if spans is None:
                    spans = [(pymupdf.Rect(s["bbox"]), s["size"]) for b in page.get_text("dict")["blocks"]
                             for ln in b.get("lines", []) for s in ln["spans"]]
                size = _form_text_size(rect, spans)
        elif r.kind == "image":
            kind, rect = "image", (pymupdf.Rect(0, 0, 1, 1) * r.ctm * tp).normalize()
        elif r.kind == "text":
            kind, rect = "text", text.get(k)
            if rect is None:
                continue
            size = sizes.get(k, 0.0)
        else:
            kind, rect = "path", r.box
        if rect.is_empty and kind != "path" or rect.width <= 0 and rect.height <= 0:
            continue
        out.append((PageObject(len(out), kind, r.name, rect, r.added, size), r))
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
    return _apply(doc, p, index, a_page)


def _apply(doc, p: pymupdf.Page, index: int, a_page: pymupdf.Matrix):
    """Apply a page-space matrix (unrotated page coordinates) to object number index."""
    tp = _to_page(p)
    a_pdf = tp * a_page * ~tp

    def edit(ops, run):
        n = run.ctm * a_pdf * ~run.ctm          # applied before the existing CTM: n x ctm = ctm x a_pdf
        body = list(ops[run.start:run.end + 1])
        ops[run.start:run.end + 1] = [_ins("q"), _ins("cm", [n.a, n.b, n.c, n.d, n.e, n.f]), *body, _ins("Q"),
                                      *_state_after(ops, run)]
    return _rewrite(doc, p, index, edit)


def _about_center(doc, page: int, index: int, m: pymupdf.Matrix):
    r = next(o.rect for o in list_objects(doc, page) if o.index == index)
    c = r.tl + (r.br - r.tl) / 2
    return _apply(doc, doc[page - 1], index,
                  pymupdf.Matrix(1, 0, 0, 1, -c.x, -c.y) * m * pymupdf.Matrix(1, 0, 0, 1, c.x, c.y))


@command("Object.Rotate")
def rotate(doc, page: int, index: int, angle: float = 90):
    """Turn an object about its centre; positive angles turn it clockwise as seen on the page."""
    return _about_center(doc, page, index, pymupdf.Matrix(angle))


@command("Object.Flip")
def flip(doc, page: int, index: int, horizontal: bool = True):
    """Mirror an object left-right (horizontal) or top-bottom about its centre."""
    return _about_center(doc, page, index, pymupdf.Matrix(-1, 0, 0, 1, 0, 0) if horizontal
                         else pymupdf.Matrix(1, 0, 0, -1, 0, 0))


@command("Object.ExportImage")
def export_image(doc, page: int, index: int, dpi: int = 300) -> tuple[bytes, str]:
    """(bytes, extension) of an object: an image's own data when it is an image XObject, else a PNG render of
    its box."""
    p = doc[page - 1]
    o = next(o for o in list_objects(doc, page) if o.index == index)
    if o.kind == "image":
        xref = next((im[0] for im in p.get_images(full=True) if im[7] == o.name), 0)
        if xref:
            img = doc.extract_image(xref)
            if img and img.get("image"):
                return img["image"], img.get("ext", "png")
    clip = o.rect * p.rotation_matrix
    return p.get_pixmap(dpi=dpi, clip=clip, alpha=False).tobytes("png"), "png"


@command("Object.Delete")
def delete(doc, page: int, index: int):
    def edit(ops, run):
        ops[run.start:run.end + 1] = _state_after(ops, run)
    return _rewrite(doc, doc[page - 1], index, edit)


@command("Object.FontSize")
def font_size(doc, page: int, index: int, size: float):
    """Give a text object another font size: it is scaled about its top-left corner, so its lines keep their
    layout and the text stays editable."""
    o = next(o for o in list_objects(doc, page) if o.index == index)
    if not o.size:
        raise ValueError("this object has no text")
    k = size / o.size
    r = o.rect
    return _apply(doc, doc[page - 1], index,
                  pymupdf.Matrix(1, 0, 0, 1, -r.x0, -r.y0) * pymupdf.Matrix(k, k) * pymupdf.Matrix(1, 0, 0, 1, r.x0, r.y0))


# ---- content added by pdfdesk ------------------------------------------------------------------------------
@contextmanager
def adding(doc, page: int):
    """Mark the content streams a page gains inside this block as added by pdfdesk (a /PdfDesk marked-content
    sequence), so the Hand tool can pick those objects up without touching the page's own art."""
    before = set(doc[page - 1].get_contents())
    yield
    for x in doc[page - 1].get_contents():
        if x not in before:
            doc.update_stream(x, MARK.encode() + b" BMC\n" + (doc.xref_stream(x) or b"") + b"\nEMC")


def _append_content(doc, page: pymupdf.Page, data: bytes):
    """Draw data on top of the page, in a fresh graphics state."""
    if not page.is_wrapped:
        page.wrap_contents()
    pymupdf.TOOLS._insert_contents(page, data, 1)


# ---- copying objects -----------------------------------------------------------------------------------------
def _set_path(doc, xref: int, path: str, value: str):
    """xref_set_key that follows indirect dictionaries along the path (it refuses them itself)."""
    parts, prefix = path.split("/"), []
    for part in parts[:-1]:
        kind, val = doc.xref_get_key(xref, "/".join(prefix + [part]))
        if kind == "xref":
            xref, prefix = int(val.split()[0]), []
        else:
            prefix.append(part)
    doc.xref_set_key(xref, "/".join(prefix + [parts[-1]]), value)


def _resource_refs(ops) -> list[tuple[str, str]]:
    """(category, name) of every named resource the instructions use."""
    out = []
    for ins in ops:
        spec = RESOURCE_OPS.get(str(ins.operator))
        if spec and ins.operands:
            cat, k = spec
            v = ins.operands[k]
            if isinstance(v, pikepdf.Name):
                out.append((cat, str(v).lstrip("/")))
    return list(dict.fromkeys(out))


def _own_resources(doc, page: pymupdf.Page):
    """Make sure the page has a /Resources of its own (not inherited), so entries can be added for it alone."""
    kind, _val = doc.xref_get_key(page.xref, "Resources")
    if kind not in ("null", None):
        return
    x = page.xref
    while True:
        kind, val = doc.xref_get_key(x, "Parent")
        if kind != "xref":
            doc.xref_set_key(page.xref, "Resources", "<<>>")
            return
        x = int(val.split()[0])
        kind, val = doc.xref_get_key(x, "Resources")
        if kind == "xref":
            doc.xref_set_key(page.xref, "Resources", doc.xref_object(int(val.split()[0]), compressed=True))
            return
        if kind == "dict":
            doc.xref_set_key(page.xref, "Resources", val)
            return


def _rename(ops, renames: dict[tuple[str, str], str]):
    for ins in ops:
        spec = RESOURCE_OPS.get(str(ins.operator))
        if spec and ins.operands:
            cat, k = spec
            v = ins.operands[k]
            if isinstance(v, pikepdf.Name) and (cat, str(v).lstrip("/")) in renames:
                ins.operands[k] = pikepdf.Name("/" + renames[(cat, str(v).lstrip("/"))])


@command("Object.Copy")
def copy(doc, page: int, index: int) -> dict:
    """An object as Object.Paste takes it (same document only): its instructions with the graphics state
    they rely on, the resources they name, the matrix from their space to the page, and its box."""
    p = doc[page - 1]
    ops, objs = _objects(doc, p)
    o, run = next(((o, r) for o, r in objs if o.index == index), (None, None))
    if run is None:
        raise IndexError(f"no object {index} on page {page}")
    body = [*run.state, *ops[run.start:run.end + 1]]
    res = {}
    for cat, name in _resource_refs(body):
        kind, val = _resource(doc, p, f"{cat}/{name}")
        if kind not in ("null", None):
            res[(cat, name)] = val
    return {"content": pikepdf.unparse_content_stream(body), "resources": res, "rect": tuple(o.rect),
            "matrix": tuple(run.ctm * _to_page(p)), "kind": o.kind, "size": o.size}


def _fit(old: pymupdf.Rect, new: pymupdf.Rect) -> pymupdf.Matrix:
    """Page-space matrix taking box old onto box new."""
    sx = new.width / old.width if old.width > 1e-6 else 1
    sy = new.height / old.height if old.height > 1e-6 else 1
    return pymupdf.Matrix(1, 0, 0, 1, -old.x0, -old.y0) * pymupdf.Matrix(sx, sy) * \
        pymupdf.Matrix(1, 0, 0, 1, new.x0, new.y0)


@command("Object.Paste")
def paste(doc, page: int, item: dict, rect=None) -> pymupdf.Rect:
    """Draw a copied object (Object.Copy, same document) on a page, in box rect (default: where it was).
    The copy is marked as added, so the Hand tool can pick it up. Returns its box."""
    p = doc[page - 1]
    ops = _parse(item["content"])
    _own_resources(doc, p)
    renames = {}
    for (cat, name), val in item["resources"].items():
        kind, cur = _resource(doc, p, f"{cat}/{name}")
        use = name
        if kind not in ("null", None) and cur != val:
            n = 0
            while _resource(doc, p, f"{cat}/pd{n}{name}")[0] not in ("null", None):
                n += 1
            use = renames[(cat, name)] = f"pd{n}{name}"
        if kind in ("null", None) or use != name:
            _set_path(doc, p.xref, f"Resources/{cat}/{use}", val)
    if renames:
        _rename(ops, renames)
    old = pymupdf.Rect(item["rect"])
    new = pymupdf.Rect(rect) if rect is not None else old
    m = pymupdf.Matrix(item["matrix"]) * _fit(old, new) * ~_to_page(p)
    data = b"q\n" + pikepdf.unparse_content_stream([_ins("cm", [m.a, m.b, m.c, m.d, m.e, m.f])]) + b"\n" + \
        pikepdf.unparse_content_stream(ops) + b"\nQ"
    with adding(doc, page):
        _append_content(doc, p, data)
    return new


@command("Object.PasteFrom")
def paste_from(doc, page: int, pdf: bytes, clip, rect) -> pymupdf.Rect:
    """Draw the part clip (unrotated page coordinates) of another document's first page in box rect: how an
    object travels between documents. Returns its box."""
    src = pymupdf.open("pdf", pdf)
    p = doc[page - 1]
    r = pymupdf.Rect(rect)
    with adding(doc, page):
        p.show_pdf_page(r * p.rotation_matrix, src, 0, clip=pymupdf.Rect(clip) * src[0].rotation_matrix,
                        keep_proportion=False)
    return r


@command("Object.Transfer")
def transfer(doc, page: int, index: int, to_page: int, rect) -> pymupdf.Rect:
    """Move an object to another page, into box rect."""
    item = copy(doc, page, index)
    new = paste(doc, to_page, item, rect)
    delete(doc, page, index)
    return new
