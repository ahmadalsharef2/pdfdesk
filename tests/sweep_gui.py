"""Not a pytest test: run it by hand. End-to-end sweep of the window: open a document, run every ribbon action and
every tool gesture with dialogs answered automatically, and print a line for every crash (EXC), error or warning
box (BOX), traceback on stderr (STDERR) and action slower than two seconds (SLOW).

    QT_QPA_PLATFORM=offscreen .venv/bin/python -u tests/sweep_gui.py [file.pdf]
"""
import contextlib
import io
import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_home = tempfile.mkdtemp(prefix="pdfdesk-sweep-")          # keep the user's settings and recent files untouched
os.environ["XDG_CONFIG_HOME"] = os.path.join(_home, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_home, "data")

import pymupdf  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QFileDialog, QInputDialog, QMenu,  # noqa: E402
                               QMessageBox)

from conftest import make_contract  # noqa: E402
from pdfdesk.commands import run as run_cmd  # noqa: E402
from pdfdesk.gui import viewer as vm  # noqa: E402
from pdfdesk.gui.app import Main  # noqa: E402

SKIP = ("exit", "close", "language", "restart", "print")    # would end the run or need a printer
SLOW_S = 2.0

app = QApplication([])
tmp = tempfile.mkdtemp(prefix="pdfdesk-sweep-files-")
pdf = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tmp, "v.pdf")
if len(sys.argv) <= 1:
    make_contract(pdf)
pdf2 = os.path.join(tmp, "w.pdf")
make_contract(pdf2, v2=True)
png = os.path.join(tmp, "img.png")
pymupdf.open(pdf2)[0].get_pixmap(dpi=40).save(png)
pfx = os.path.join(tmp, "id.pfx")
run_cmd("Sign.CreateID", pfx, "Sweep Tester", "pw")
os.makedirs(os.path.join(tmp, "out"), exist_ok=True)
_n = [0]


def _save_name(*a, **k):
    _n[0] += 1
    flt = (a[3] if len(a) > 3 else k.get("filter", "")) or ""
    ext = next((e for e in (".xml", ".txt", ".docx", ".xlsx", ".pptx", ".rtf", ".html", ".png", ".jpg", ".json",
                            ".fdf", ".xfdf", ".csv")
                if e[1:] in flt.lower()), ".pdf")
    return os.path.join(tmp, "out", f"o{_n[0]}{ext}"), ""


def _open_name(*a, **k):
    flt = ((a[3] if len(a) > 3 else k.get("filter", "")) or "").lower()
    if "pfx" in flt or "p12" in flt:
        return pfx, ""
    if "image" in flt or "png" in flt:
        return png, ""
    return pdf2, ""


def _exec_once(self):
    """Accept a dialog the first time; a dialog that asks again (invalid input) is then cancelled."""
    if getattr(self, "_swept", False):
        return QDialog.Rejected
    self._swept = True
    return QDialog.Accepted


boxes: list[str] = []
QFileDialog.getSaveFileName = staticmethod(_save_name)
QFileDialog.getOpenFileName = staticmethod(_open_name)
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([pdf2, pdf], ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: tmp)
QInputDialog.getText = staticmethod(lambda *a, **k: ("pw", True))
QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("some text", True))
QInputDialog.getInt = staticmethod(lambda *a, **k: (2, True))
QInputDialog.getItem = staticmethod(lambda p, t, lab, items, *a, **k: (items[0] if items else "", True))
QColorDialog.getColor = staticmethod(lambda *a, **k: QColor(200, 30, 30))
for _name in ("information", "warning", "critical"):
    setattr(QMessageBox, _name, staticmethod(
        lambda p, t, text, *a, _n=_name, **k: boxes.append(f"{_n}: {t}: {text}") or QMessageBox.Ok))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.about = staticmethod(lambda *a, **k: None)
QDialog.exec = _exec_once
QMenu.exec = lambda self, *a, **k: None

w = Main()
w.show()
app.processEvents()
problems: list[str] = []


def report(line: str):
    problems.append(line)
    print(line, flush=True)


def attempt(label: str, fn):
    if w.cur() is None:
        w.open_path(pdf)
    boxes.clear()
    err = io.StringIO()
    t0 = time.time()
    try:
        with contextlib.redirect_stderr(err):
            fn()
            app.processEvents()
    except Exception:  # noqa: BLE001
        report(f"EXC  {label}\n{traceback.format_exc()}")
        return
    dt = time.time() - t0
    if boxes:
        report(f"BOX  {label}: " + " | ".join(boxes))
    if "Traceback" in err.getvalue():
        report(f"STDERR {label}: {err.getvalue()[-800:]}")
    if dt > SLOW_S:
        report(f"SLOW {label}: {dt:.1f} s")


labels = [lab for lab in w.ribbon._catalog if not any(s in lab.lower() for s in SKIP)]
print(f"{len(labels)} ribbon actions", flush=True)
for lab in labels:
    attempt(lab, w.ribbon._catalog[lab])

P = pymupdf.Point
for t in sorted(vm.RECT_TOOLS):
    attempt(f"tool {t}", lambda t=t: w.on_tool({"tool": t, "page": 1, "point": P(100, 100),
                                                "rect": pymupdf.Rect(100, 100, 220, 160)}))
for t in sorted(vm.LINE_TOOLS | vm.MARKUP_TOOLS):
    attempt(f"tool {t}", lambda t=t: w.on_tool({"tool": t, "page": 1, "start": P(72, 105), "stop": P(170, 115)}))
for t in sorted(vm.POINT_TOOLS):
    attempt(f"tool {t}", lambda t=t: w.on_tool({"tool": t, "page": 1, "point": P(300, 300)}))
for t in sorted(vm.POLY_TOOLS):
    attempt(f"tool {t}", lambda t=t: w.on_tool({"tool": t, "page": 1, "points": [P(300, 400), P(400, 400), P(350, 450)]}))
attempt("tool pencil", lambda: w.on_tool({"tool": "pencil", "page": 1, "strokes": [[P(10, 10), P(50, 50), P(80, 20)]]}))
attempt("undo x3", lambda: [w.undo() for _ in range(3)])
attempt("redo x3", lambda: [w.redo() for _ in range(3)])
attempt("save", w.save)
attempt("save as", w.save_as)
print("no problems found" if not problems else f"{len(problems)} problems", flush=True)
