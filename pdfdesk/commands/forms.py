"""Form commands: list, fill, create fields, recognise fields, import/export data (JSON, FDF, XFDF), flatten."""
from __future__ import annotations

import json
import re
from xml.sax.saxutils import escape

import pymupdf

from .pages import parse_range
from .registry import command

TYPES = {"text": pymupdf.PDF_WIDGET_TYPE_TEXT, "checkbox": pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
         "radio": pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, "combo": pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
         "list": pymupdf.PDF_WIDGET_TYPE_LISTBOX, "button": pymupdf.PDF_WIDGET_TYPE_BUTTON,
         "signature": pymupdf.PDF_WIDGET_TYPE_SIGNATURE}
TYPE_NAMES = {v: k for k, v in TYPES.items()}


def _widgets(doc):
    for page in doc:
        for w in page.widgets():
            yield page, w


def _value(w):
    if w.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
        return w.field_value not in (False, "Off", "", None)
    return w.field_value


@command("Form.List")
def list_fields(doc) -> list[dict]:
    return [{"name": w.field_name, "type": TYPE_NAMES.get(w.field_type, "unknown"), "value": _value(w),
             "page": page.number + 1, "rect": tuple(w.rect), "xref": w.xref,
             "options": list(w.choice_values or []), "readonly": bool(w.field_flags & 1)}
            for page, w in _widgets(doc)]


def _set_radio(w, on: bool):
    """Radio kids are switched through /AS and the parent's /V; Widget.update() would rewrite the on-state."""
    doc = w.parent.parent
    state = w.on_state() if on else "Off"
    doc.xref_set_key(w.xref, "AS", f"/{state}")
    par = doc.xref_get_key(w.xref, "Parent")
    if par[0] == "xref":
        pxref = int(par[1].split()[0])
        if on:
            doc.xref_set_key(pxref, "V", f"/{state}")
            for k in re.findall(r"(\d+) 0 R", doc.xref_get_key(pxref, "Kids")[1]):
                if int(k) != w.xref:
                    doc.xref_set_key(int(k), "AS", "/Off")
        elif doc.xref_get_key(pxref, "V")[1] == f"/{w.on_state()}":
            doc.xref_set_key(pxref, "V", "/Off")


def _set(w, value):
    t = w.field_type
    if t == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
        return _set_radio(w, value if isinstance(value, bool) else str(value).lower() not in ("", "off", "no", "false", "0"))
    if t == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
        on = value if isinstance(value, bool) else str(value).lower() not in ("", "off", "no", "false", "0")
        w.field_value = w.on_state() if on else "Off"
    elif t == pymupdf.PDF_WIDGET_TYPE_LISTBOX and isinstance(value, list):
        w.field_value = value
    else:
        w.field_value = "" if value is None else str(value)
    w.update()


@command("Form.Fill")
def fill(doc, values: dict) -> int:
    """values: {field name: value}. Radio groups take True on the widget whose on-state matches, or the
    on-state name itself. Returns how many widgets were set."""
    n = 0
    for _, w in _widgets(doc):
        if w.field_name not in values:
            continue
        v = values[w.field_name]
        if w.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON and isinstance(v, str):
            if v == w.on_state():
                _set_radio(w, True)
            elif v == "Off":
                _set_radio(w, False)
            n += 1
            continue
        _set(w, v)
        n += 1
    return n


@command("Form.SetField")
def set_field(doc, page: int, xref: int, value):
    for w in doc[page - 1].widgets():
        if w.xref == xref:
            _set(w, value)
            return
    raise KeyError(f"no field with xref {xref} on page {page}")


@command("Form.Reset")
def reset(doc, names: list[str] | None = None):
    for _, w in _widgets(doc):
        if names is None or w.field_name in names:
            _set(w, False if w.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                                               pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON) else "")


@command("Form.AddField")
def add_field(doc, page: int, rect, kind: str = "text", name: str | None = None, value=None,
              options: list[str] | None = None, fontsize: float = 0, multiline: bool = False,
              required: bool = False, tooltip: str = "", group: str | None = None):
    """Create a field. kind: text, checkbox, radio, combo, list, button, signature. Radio buttons in one group
    share `group` as the field name; each gets its own on-state (`name`)."""
    pg = doc[page - 1]
    w = pymupdf.Widget()
    w.field_type = TYPES[kind]
    w.rect = pymupdf.Rect(rect)
    existing = {x["name"] for x in list_fields(doc)}
    if kind == "radio":
        w.field_name = group or name or "Group1"
        w.button_caption = name or f"Choice{sum(1 for x in pg.widgets() if x.field_name == w.field_name) + 1}"
    else:
        base = name or f"{kind.capitalize()}{len(existing) + 1}"
        w.field_name, k = base, 1
        while w.field_name in existing:
            k += 1
            w.field_name = f"{base}_{k}"
    w.text_fontsize = fontsize
    w.border_color, w.border_width = (0.45, 0.45, 0.55), 0.8
    w.fill_color = (0.93, 0.95, 1.0)
    if tooltip:
        w.field_label = tooltip
    flags = 0
    if required:
        flags |= pymupdf.PDF_FIELD_IS_REQUIRED
    if multiline and kind == "text":
        flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
    w.field_flags = flags
    if kind in ("combo", "list"):
        w.choice_values = options or ["Option 1", "Option 2"]
        w.field_value = value if value is not None else w.choice_values[0]
    elif kind == "checkbox":
        w.field_value = bool(value)
    elif kind == "radio":
        w.field_value = bool(value)
    elif kind == "button":
        w.button_caption = value or name or "Button"
    elif value is not None:
        w.field_value = str(value)
    pg.add_widget(w)
    if kind == "radio":
        _name_radio_state(doc, w, re.sub(r"[^\w.-]", "_", w.button_caption))
    return w.field_name


def _name_radio_state(doc, w, state: str):
    """PyMuPDF names every radio on-state /True, which links all buttons of a group; give each its own."""
    ap = doc.xref_get_key(w.xref, "AP/N")[1]
    on = [k for k in re.findall(r"/([^\s/<>]+)\s+\d+ 0 R", ap) if k != "Off"]
    if not on or on[0] == state:
        return
    for key in ("AP/N", "AP/D"):
        val = doc.xref_get_key(w.xref, key)
        if val[0] == "dict":
            doc.xref_set_key(w.xref, key, val[1].replace(f"/{on[0]} ", f"/{state} "))
    was_on = doc.xref_get_key(w.xref, "AS")[1] == f"/{on[0]}"
    doc.xref_set_key(w.xref, "AS", f"/{state}" if was_on else "/Off")
    par = doc.xref_get_key(w.xref, "Parent")
    if was_on and par[0] == "xref":
        doc.xref_set_key(int(par[1].split()[0]), "V", f"/{state}")


@command("Form.DeleteField")
def delete_field(doc, names: list[str] | str):
    names = [names] if isinstance(names, str) else names
    for page in doc:
        for w in list(page.widgets()):
            if w.field_name in names:
                page.delete_widget(w)


UNDERSCORES = re.compile(r"_{4,}")
BOXES = re.compile(r"[☐□❑❒◻]|\[\s?\]")


@command("Form.Recognize")
def recognize(doc, pages: str | None = None) -> list[str]:
    """Foxit's "Run Form Field Recognition": blank lines (____) become text fields, boxes (☐ or [ ]) become
    check boxes. The word before a blank is used as the field name."""
    made = []
    taken = [pymupdf.Rect(x["rect"]) for x in list_fields(doc)]
    for i in parse_range(pages, doc.page_count):
        pg = doc[i]
        for b in pg.get_text("rawdict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    chars = span["chars"]
                    text = "".join(c["c"] for c in chars)
                    for rx, kind in ((UNDERSCORES, "text"), (BOXES, "checkbox")):
                        for m in rx.finditer(text):
                            r = pymupdf.Rect()
                            for c in chars[m.start():m.end()]:
                                r |= pymupdf.Rect(c["bbox"])
                            if kind == "text":
                                r.y0 = r.y1 - max(r.height, span["size"] * 1.3)
                            if any(r.intersects(t) for t in taken):
                                continue
                            before = re.findall(r"\w+", text[:m.start()])
                            after = re.findall(r"\w+", text[m.end():])
                            nm = before[-1] if before else (after[0] if after and kind == "checkbox" else None)
                            made.append(add_field(doc, i + 1, r, kind, name=nm))
                            taken.append(r)
    return made


@command("Form.Flatten")
def flatten(doc):
    """Bake field appearances into the page content; the fields are removed."""
    doc.bake(annots=False, widgets=True)


@command("Form.Calculate")
def calculate(doc, target: str, sources: list[str], op: str = "sum"):
    """Simple calculated field (Foxit's Calculate tab): sum, product, average, min or max of other fields."""
    vals = {w.field_name: w.field_value for _, w in _widgets(doc)}
    nums = []
    for s in sources:
        try:
            nums.append(float(str(vals.get(s, "")).replace(",", "") or 0))
        except ValueError:
            nums.append(0.0)
    res = {"sum": sum(nums), "average": sum(nums) / len(nums) if nums else 0, "min": min(nums, default=0),
           "max": max(nums, default=0), "product": __import__("math").prod(nums)}[op]
    fill(doc, {target: f"{res:g}"})
    return res


# ---- data exchange -------------------------------------------------------------------------------------
def _data(doc) -> dict:
    out = {}
    for _, w in _widgets(doc):
        if w.field_type in (pymupdf.PDF_WIDGET_TYPE_BUTTON, pymupdf.PDF_WIDGET_TYPE_SIGNATURE):
            continue
        if w.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
            if _value(w):
                out[w.field_name] = w.on_state()
            else:
                out.setdefault(w.field_name, "Off")
        elif w.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
            out[w.field_name] = w.on_state() if _value(w) else "Off"
        else:
            out[w.field_name] = w.field_value
    return out


def _pdfstr(s: str) -> str:
    return "(" + str(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


@command("Form.Export")
def export_data(doc, path: str, source: str = "document.pdf"):
    """Write form data to .json, .fdf, .xfdf or .csv (chosen by extension)."""
    data = _data(doc)
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "json":
        text = json.dumps(data, indent=2, ensure_ascii=False)
    elif ext == "xfdf":
        fields = "\n".join(f'    <field name="{escape(k, {chr(34): "&quot;"})}"><value>{escape(str(v))}</value></field>'
                           for k, v in data.items())
        text = ('<?xml version="1.0" encoding="UTF-8"?>\n<xfdf xmlns="http://ns.adobe.com/xfdf/" xml:space="preserve">\n'
                f'  <f href="{escape(source)}"/>\n  <fields>\n{fields}\n  </fields>\n</xfdf>\n')
    elif ext == "fdf":
        def val(k, v):
            on = k in _buttons(doc)
            return f"/{v}" if on and v else _pdfstr(v if not isinstance(v, list) else ", ".join(v))
        body = "".join(f"<< /T {_pdfstr(k)} /V {val(k, v)} >>\n" for k, v in data.items())
        text = f"%FDF-1.2\n1 0 obj\n<< /FDF << /F {_pdfstr(source)} /Fields [\n{body}] >> >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    elif ext == "csv":
        import csv
        import io
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow(data.keys())
        wr.writerow([v if not isinstance(v, list) else ";".join(v) for v in data.values()])
        text = buf.getvalue()
    else:
        raise ValueError(f"unsupported form data format: .{ext}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return data


def _buttons(doc) -> set[str]:
    return {w.field_name for _, w in _widgets(doc) if w.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                                                                     pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON)}


def read_data(path: str) -> dict:
    raw = open(path, "rb").read()
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "json":
        return json.loads(raw)
    if ext == "xfdf":
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw)
        out = {}
        for f in root.iter():
            if f.tag.rsplit("}", 1)[-1] == "field":
                v = [x.text or "" for x in f if x.tag.rsplit("}", 1)[-1] == "value"]
                out[f.get("name")] = v[0] if len(v) == 1 else (v or "")
        return out
    if ext == "fdf":
        text = raw.decode("latin-1")
        out = {}
        for m in re.finditer(r"/T\s*\((?P<t>(?:\\.|[^\\)])*)\)\s*/V\s*(?:\((?P<s>(?:\\.|[^\\)])*)\)|/(?P<n>\w+))", text):
            unesc = lambda s: re.sub(r"\\(.)", r"\1", s)  # noqa: E731
            out[unesc(m["t"])] = unesc(m["s"]) if m["s"] is not None else m["n"]
        return out
    if ext == "csv":
        import csv
        rows = list(csv.reader(open(path, encoding="utf-8")))
        return dict(zip(rows[0], rows[1])) if len(rows) > 1 else {}
    raise ValueError(f"unsupported form data format: .{ext}")


@command("Form.Import")
def import_data(doc, path: str) -> int:
    data = read_data(path)
    buttons = _buttons(doc)
    for k, v in list(data.items()):
        if k in buttons and v in ("Off", ""):
            data[k] = False
    return fill(doc, data)
