"""What the browser and phone apps call (web/). Python runs on the device there, inside Pyodide; the page
view and its controls are the app's own. Documents stay on this side, the interface gets plain JSON and bytes,
and every edit is a command from pdfdesk.commands run by name, as the desktop window does.

Pages are 0-based in the functions here (they index the view) and 1-based in commands, as everywhere else.
Coordinates are unrotated page points; `info` gives each page's rotation matrix for drawing them."""
from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import os
import tempfile
import zipfile

import pymupdf

from . import lang
from .commands import COMMANDS, comment, convert, edit, forms
from .commands import search as search_cmd
from .core import license
from .core import security as sec
from .lang import tr

WORK = tempfile.mkdtemp(prefix="pdfdesk-")
UNDO_LIMIT = 15
UNDO_BYTES = 192 * 2**20          # a phone has far less memory to spare than a desktop
RESIZABLE = {pymupdf.PDF_ANNOT_SQUARE, pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_FREE_TEXT, pymupdf.PDF_ANNOT_STAMP}
# commands that are left out where their library has no build for the browser
NEEDS = {"Object.": "pikepdf", "Ocr.": "paddleocr", "Convert.ToWord": "pdf2docx", "Convert.ToPDFA": "ocrmypdf",
         "Convert.ToRtf": None, "Convert.ToExcel": "openpyxl", "Convert.ToPowerPoint": "pptx",
         "Sign.Digital": "pyhanko", "Sign.Validate": "pyhanko", "Sign.CreateID": "cryptography",
         "Invoice.Embed": "pikepdf", "Invoice.Create": "pikepdf", "Search.Folder": None}


class NeedsPassword(Exception):
    pass


@dataclasses.dataclass
class Session:
    doc: pymupdf.Document
    name: str
    path: str                                   # its file in the work folder: opened from there, saved there
    password: str | None = None
    security: sec.Security | None = None
    readonly: bool = False
    modified: bool = False
    undo: list = dataclasses.field(default_factory=list)      # (label, bytes), as the desktop view keeps them
    redo: list = dataclasses.field(default_factory=list)

    def reopen(self, data: bytes):
        d = pymupdf.open("pdf", data)
        if d.needs_pass and self.password:
            d.authenticate(self.password)
        self.doc = d

    def checkpoint(self, label: str):
        self.undo.append((label, self.doc.tobytes()))
        while len(self.undo) > UNDO_LIMIT or (len(self.undo) > 2 and sum(len(d) for _l, d in self.undo) > UNDO_BYTES):
            self.undo.pop(0)
        self.redo.clear()

    def step(self, src: list, dst: list) -> str | None:
        if not src:
            return None
        label, data = src.pop()
        dst.append((label, self.doc.tobytes()))
        self.reopen(data)
        self.modified = True
        return label

    def rollback(self):
        if self.undo:
            self.reopen(self.undo.pop()[1])


SESSIONS: dict[int, Session] = {}
_next = [1]
_unlocked = False                 # set by activate() once the product key was given


def _add(doc: pymupdf.Document, name: str, path: str | None = None, **kw) -> int:
    sid = _next[0]
    _next[0] += 1
    if path is None:
        os.makedirs(os.path.join(WORK, str(sid)), exist_ok=True)
        path = os.path.join(WORK, str(sid), os.path.basename(name) or "document.pdf")
    SESSIONS[sid] = Session(doc, name, path, **kw)
    return sid


def _plain(v):
    """A command's result as JSON can carry it; a new document becomes a session."""
    if isinstance(v, pymupdf.Document):
        return {"doc": info(_add(v, tr("untitled") + ".pdf", modified=True))}
    if isinstance(v, (pymupdf.Rect, pymupdf.Point, pymupdf.Quad, pymupdf.Matrix)):
        return list(v)
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _plain(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_plain(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return None
    return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)


# ---- languages and what this build can do ---------------------------------------------------------------
def strings(code: str) -> dict:
    """Switch the language; returns its table for the interface (English text -> translation)."""
    lang.set_language(code)
    return {"code": lang.language(), "rtl": lang.is_rtl(), "table": dict(lang._table)}


def activate(key: str = "") -> bool:
    """Unlock this build with the product key; until then only this and strings() answer."""
    global _unlocked
    _unlocked = _unlocked or license.valid(key)
    return _unlocked


def available() -> list[str]:
    """The commands this build can run."""
    def has(lib):
        return lib == "" or (lib is not None and importlib.util.find_spec(lib) is not None)
    return [name for name in sorted(COMMANDS)
            if has(next((lib for prefix, lib in NEEDS.items() if name.startswith(prefix)), ""))]


# ---- documents ------------------------------------------------------------------------------------------
def _convertible(path: str):
    """Office files go through LibreOffice, which a browser or a phone does not have: say so plainly."""
    if os.path.splitext(path)[1].lower() not in convert.OFFICE_EXT:
        return
    try:
        convert._soffice()
    except RuntimeError:
        raise ValueError(tr("Word, Excel and PowerPoint files can only be converted in the desktop edition.")) from None


def open_file(path: str, name: str, password: str | None = None) -> dict:
    """Open a file from the work folder: a PDF as it is, anything else converted to one."""
    if not name.lower().endswith(".pdf"):
        _convertible(path)
        doc = COMMANDS["Convert.FromFile"](path)
        return info(_add(doc, os.path.splitext(name)[0] + ".pdf", modified=True))
    doc = pymupdf.open(path)
    auth = 0
    if doc.needs_pass:
        auth = doc.authenticate(password) if password is not None else 0
        if not auth:
            doc.close()
            raise NeedsPassword(tr("That password is not correct.") if password is not None else name)
    return info(_add(doc, name, path, password=password, security=sec.from_open(doc, password, auth),
                     readonly=sec.restricted(doc, auth)))


def create(paths: list[str], name: str | None = None) -> dict:
    """A new document from one or more files (images, text, HTML, PDFs)."""
    for p in paths:
        _convertible(p)
    doc = COMMANDS["Convert.Combine"](paths) if len(paths) > 1 else COMMANDS["Convert.FromFile"](paths[0])
    stem = os.path.splitext(os.path.basename(paths[0]))[0]
    return info(_add(doc, name or stem + ".pdf", modified=True))


def blank(width: float = 595, height: float = 842) -> dict:
    doc = pymupdf.open()
    doc.new_page(width=width, height=height)
    return info(_add(doc, tr("untitled") + ".pdf", modified=True))


def close(sid: int):
    s = SESSIONS.pop(sid, None)
    if s:
        s.doc.close()
        if os.path.isfile(s.path):
            os.remove(s.path)


def state(sid: int) -> dict:
    """What the title and the undo buttons show; cheap, so the interface asks after every edit."""
    s = SESSIONS[sid]
    return {"id": sid, "name": s.name, "modified": s.modified, "readonly": s.readonly,
            "protected": s.security is not None, "undo": s.undo[-1][0] if s.undo else None,
            "redo": s.redo[-1][0] if s.redo else None}


def info(sid: int) -> dict:
    """state plus the pages: [width, height, rotation, *rotation matrix] each, sizes as displayed."""
    d = SESSIONS[sid].doc
    pages = [[p.rect.width, p.rect.height, p.rotation, *p.rotation_matrix] for p in d]
    return {**state(sid), "pages": pages, "form": bool(d.is_form_pdf), "signed": d.get_sigflags() > 0,
            "bookmarks": len(d.get_toc(simple=True))}


def render(sid: int, page: int, scale: float, clip=None) -> tuple[dict, bytes]:
    """A page (or the part `clip`, in displayed page points) as RGBA pixels."""
    p = SESSIONS[sid].doc[page]
    pix = p.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, clip=clip)
    pix = pymupdf.Pixmap(pix, 1)
    return {"width": pix.width, "height": pix.height}, pix.samples


def words(sid: int, page: int) -> list:
    return [list(w[:7]) for w in SESSIONS[sid].doc[page].get_text("words")]


def page_items(sid: int, page: int) -> dict:
    """What can be tapped on a page: comments, form fields and links."""
    s = SESSIONS[sid]
    doc, p = s.doc, s.doc[page]
    comments = []
    for a in p.annots() or []:
        if a.type[0] in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_LINK) \
                or a.flags & comment.HIDDEN_FLAGS:
            continue
        comments.append({"xref": a.xref, "type": a.type[1], "kind": comment._kind(doc, a), "rect": list(a.rect),
                         "content": a.info.get("content", ""), "author": a.info.get("title", ""),
                         "color": list(comment._color(doc, a)), "resizable": a.type[0] in RESIZABLE})
    fields = []
    for w in p.widgets():
        opts = [o[1] if isinstance(o, (list, tuple)) else o for o in (w.choice_values or [])]
        fields.append({"xref": w.xref, "type": forms.TYPE_NAMES.get(w.field_type, "unknown"), "rect": list(w.rect),
                       "name": w.field_name, "label": forms._label(w), "value": forms._value(w), "options": opts,
                       "readonly": bool(w.field_flags & 1), "multiline": bool(w.field_flags & (1 << 12)),
                       "fontsize": w.text_fontsize or 0})
    links = []
    for ln in p.get_links():
        item = {"rect": list(ln["from"])}
        if ln["kind"] in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED) and ln.get("page") is not None \
                and 0 <= ln["page"] < doc.page_count:
            item["page"] = ln["page"]
            if ln.get("to") is not None:
                pt = pymupdf.Point(ln["to"])
                if ln["kind"] == pymupdf.LINK_NAMED:     # a named destination comes in PDF space (y up)
                    pt = pt * doc[ln["page"]].transformation_matrix
                item["y"] = pt.y
        elif ln.get("uri"):
            item["uri"] = ln["uri"]
        else:
            continue
        links.append(item)
    return {"comments": comments, "fields": fields, "links": links}


def line_at(sid: int, page: int, point) -> dict | None:
    """The text line under a point, for Edit Text."""
    ln = edit.line_at(SESSIONS[sid].doc, page + 1, point)
    return ln and {"text": ln.text, "rect": list(ln.rect), "size": ln.size, "color": list(ln.color)}


def find(sid: int, text: str) -> list:
    """Matches in reading order: [[page, [rect, ...]], ...]."""
    out = []
    for p in SESSIONS[sid].doc:
        hits = search_cmd.find(p, text)
        if hits:
            out.append([p.number, [list(r) for r in hits]])
    return out


def bookmarks(sid: int) -> list:
    return [list(t) for t in SESSIONS[sid].doc.get_toc(simple=True)]


def comments(sid: int) -> list:
    return _plain(COMMANDS["Comment.List"](SESSIONS[sid].doc))


# ---- edits ----------------------------------------------------------------------------------------------
def run(sid: int, name: str, args: dict | None = None, label: str | None = None):
    """Run a command that changes the document; it becomes one undo step."""
    s = SESSIONS[sid]
    if s.readonly:
        raise PermissionError(tr("This document is read only."))
    s.checkpoint(label or name)
    try:
        res = COMMANDS[name](s.doc, **(args or {}))
    except Exception:
        s.rollback()
        raise
    s.modified = True
    return _plain(res)


def query(sid: int, name: str, args: dict | None = None):
    """Run a command that only reads the document, or returns a new one (Pages.Extract)."""
    return _plain(COMMANDS[name](SESSIONS[sid].doc, **(args or {})))


def undo(sid: int) -> str | None:
    s = SESSIONS[sid]
    return s.step(s.undo, s.redo)


def redo(sid: int) -> str | None:
    s = SESSIONS[sid]
    return s.step(s.redo, s.undo)


# ---- saving ---------------------------------------------------------------------------------------------
def protect(sid: int, user_pw: str, owner_pw: str | None = None, allow_print=True, allow_copy=True,
            allow_modify=False, allow_annotate=True):
    """Password protection, applied at the next save."""
    s = SESSIONS[sid]
    perm = sec.permissions(allow_print, allow_copy, allow_modify, allow_annotate)
    s.security = sec.Security(user_pw, owner_pw or user_pw, perm)
    s.readonly, s.modified = False, True


def unprotect(sid: int):
    s = SESSIONS[sid]
    if s.readonly:
        raise PermissionError(tr("Open the document with its permissions password first."))
    s.security, s.modified = None, True


def save(sid: int, user_pw: str | None = None, owner_pw: str | None = None) -> tuple[dict, bytes]:
    """The document as a file. A protected file opened with one of its two passwords needs the other to stay
    protected: `need` then says which, and nothing is written."""
    s = SESSIONS[sid]
    q = s.security
    if q is not None and not q.complete:
        if s.readonly:
            raise PermissionError(tr("This document is read only."))
        if q.user_pw is None:
            if user_pw is None:
                return {"need": "open"}, b""
            q.user_pw = user_pw
        elif owner_pw:
            q.owner_pw = owner_pw
        else:
            return {"need": "permissions"}, b""
    s.doc = sec.save(s.doc, s.path, q, incremental=True)
    s.modified = False
    with open(s.path, "rb") as f:
        return {"name": s.name}, f.read()


def copy(sid: int) -> tuple[dict, bytes]:
    """The document as it is now, for printing; saving state is left alone."""
    s = SESSIONS[sid]
    return {"name": s.name}, s.doc.tobytes(garbage=3, deflate=True)


def rename(sid: int, name: str):
    SESSIONS[sid].name = name if name.lower().endswith(".pdf") else name + ".pdf"


def _files(folder: str, stem: str) -> tuple[dict, bytes]:
    """One written file as it is, several as a zip."""
    names = sorted(os.listdir(folder))
    if len(names) == 1:
        with open(os.path.join(folder, names[0]), "rb") as f:
            return {"name": names[0]}, f.read()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.write(os.path.join(folder, n), n)
    return {"name": stem + ".zip"}, buf.getvalue()


def export(sid: int, kind: str, pages: str | None = None, dpi: int = 150, every: int = 1) -> tuple[dict, bytes]:
    """Another format of the document: png, jpg, text, html, excel, powerpoint, or split / extract as PDF."""
    s = SESSIONS[sid]
    stem = os.path.splitext(s.name)[0]
    with tempfile.TemporaryDirectory(dir=WORK) as out:
        if kind in ("png", "jpg"):
            for i, path in enumerate(COMMANDS["Convert.ToImages"](s.doc, out, kind, dpi, pages)):
                os.rename(path, os.path.join(out, f"{stem}_{i + 1:03d}.{kind}"))    # the document has no file name
        elif kind in ("text", "html", "excel", "powerpoint"):
            ext = {"text": "txt", "html": "html", "excel": "xlsx", "powerpoint": "pptx"}[kind]
            name = {"text": "Convert.ToText", "html": "Convert.ToHtml", "excel": "Convert.ToExcel",
                    "powerpoint": "Convert.ToPowerPoint"}[kind]
            COMMANDS[name](s.doc, os.path.join(out, f"{stem}.{ext}"), pages)
        elif kind == "extract":
            COMMANDS["Pages.Extract"](s.doc, pages).save(os.path.join(out, f"{stem}_{pages.replace(',', '_').replace(' ', '')}.pdf"), garbage=3, deflate=True)
        elif kind == "split":
            for part, d in COMMANDS["Pages.Split"](s.doc, every=every):
                d.save(os.path.join(out, f"{stem}_{part}.pdf"), garbage=3, deflate=True)
        else:
            raise ValueError(kind)
        return _files(out, stem)


# ---- one entry point for the worker ---------------------------------------------------------------------
API = {f.__name__: f for f in (strings, activate, available, open_file, create, blank, close, state, info, render, words,
                               page_items, line_at, find, bookmarks, comments, run, query, undo, redo, protect, unprotect, save, copy, rename,
                               export)}


def call(fn: str, args: str) -> tuple[str, bytes | None]:
    """Call an API function with JSON keyword arguments. Returns (JSON, bytes or None); errors come back as
    {"error": message, "kind": exception name} so the interface can show them."""
    try:
        if not _unlocked and fn not in ("strings", "activate"):
            raise PermissionError(tr("Enter the product key to use pdfdesk."))
        res = API[fn](**json.loads(args))
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e) or type(e).__name__, "kind": type(e).__name__}), None
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], (bytes, bytearray)):
        return json.dumps({"ok": res[0]}), bytes(res[1])
    return json.dumps({"ok": res}), None
