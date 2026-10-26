"""Dialogs for the ribbon commands."""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from ..core import fonts

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pdfdesk"
IDS = DATA / "ids"
SIGS = DATA / "signatures.json"
SIGNER = DATA / "signer.json"


def _buttons(dlg: QDialog, layout):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    layout.addWidget(bb)
    return bb


# ---- text entry --------------------------------------------------------------------------------------
class TextDialog(QDialog):
    def __init__(self, parent, title: str, label: str, text: str = "", size: float | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(label))
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumSize(380, 110)
        v.addWidget(self.edit)
        self.size = None
        if size is not None:
            row = QHBoxLayout()
            row.addWidget(QLabel("Font size:"))
            self.size = QDoubleSpinBox(minimum=4, maximum=144, value=size)
            row.addWidget(self.size)
            row.addStretch()
            v.addLayout(row)
        _buttons(self, v)

    @staticmethod
    def ask(parent, title, label, text="", size=None):
        d = TextDialog(parent, title, label, text, size)
        d.edit.setFocus()
        if d.exec() != QDialog.Accepted or not d.edit.toPlainText().strip():
            return None
        t = d.edit.toPlainText().rstrip("\n")
        return (t, d.size.value()) if size is not None else t


# ---- signatures ----------------------------------------------------------------------------------------
class DrawPad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 150)
        self.strokes: list[list[tuple[float, float]]] = []
        self.setStyleSheet("background:white")
        self.setAttribute(Qt.WA_StyledBackground, True)

    def mousePressEvent(self, e):
        self.strokes.append([(e.position().x(), e.position().y())])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.LeftButton:
            self.strokes[-1].append((e.position().x(), e.position().y()))
            self.update()

    def clear(self):
        self.strokes = []
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.white)
        p.setPen(QPen(Qt.gray, 1, Qt.DashLine))
        p.drawLine(20, self.height() - 30, self.width() - 20, self.height() - 30)
        p.setPen(QPen(Qt.darkBlue, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            if len(s) > 1:
                path = QPainterPath(QPointF(*s[0]))
                for q in s[1:]:
                    path.lineTo(QPointF(*q))
                p.drawPath(path)


class SignerDetails(QGroupBox):
    """Signer profile: one checkbox + text per detail; checked ones go in the caption under the signature."""
    LABELS = {"name": "Full name", "position": "Position", "company": "Company", "email": "Email",
              "phone": "Phone", "address": "Address", "date": "Date (signing day)"}

    def __init__(self, default_name: str = ""):
        super().__init__("Details under the signature")
        prof = signer_profile()
        prof.setdefault("name", default_name)
        show = set(prof.get("show", ()))
        g = QGridLayout(self)
        self.checks, self.edits = {}, {}
        for i, (k, label) in enumerate(self.LABELS.items()):
            self.checks[k] = QCheckBox(label, checked=k in show)
            g.addWidget(self.checks[k], i, 0)
            if k != "date":
                self.edits[k] = QLineEdit(prof.get(k, ""))
                self.edits[k].textEdited.connect(lambda _t, c=self.checks[k]: c.setChecked(True))
                g.addWidget(self.edits[k], i, 1)
        self.layout_box = QComboBox()
        self.layout_box.addItem("One detail per line", "lines")
        self.layout_box.addItem("Compact: two lines", "compact")
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(prof.get("layout", "lines"))))
        g.addWidget(QLabel("Layout"), len(self.LABELS), 0)
        g.addWidget(self.layout_box, len(self.LABELS), 1)
        g.setColumnStretch(1, 1)

    def profile(self) -> dict:
        prof = {k: e.text().strip() for k, e in self.edits.items()}
        prof["show"] = [k for k, c in self.checks.items() if c.isChecked()]
        prof["layout"] = self.layout_box.currentData()
        return prof


def signer_profile() -> dict:
    """Default: no caption; contact details are only shown when the user ticks them."""
    try:
        return json.loads(SIGNER.read_text())
    except (OSError, ValueError):
        return {"show": []}


def save_signer_profile(prof: dict):
    SIGNER.parent.mkdir(parents=True, exist_ok=True)
    SIGNER.write_text(json.dumps(prof))
    os.chmod(SIGNER, 0o600)


class SignerDialog(QDialog):
    def __init__(self, parent, default_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Signer Details")
        v = QVBoxLayout(self)
        self.details = SignerDetails(default_name)
        v.addWidget(self.details)
        _buttons(self, v)

    @staticmethod
    def ask(parent, default_name=""):
        d = SignerDialog(parent, default_name)
        if d.exec() == QDialog.Accepted:
            save_signer_profile(d.details.profile())


class SignatureDialog(QDialog):
    """Create a Fill & Sign signature: typed, drawn or from an image. Returns a spec dict."""

    def __init__(self, parent, default_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Create Signature")
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # type
        tw = QWidget()
        tl = QVBoxLayout(tw)
        self.name = QLineEdit(default_name, placeholderText="Your name")
        self.preview = QLabel()
        self.preview.setMinimumHeight(80)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:white;color:#00008c")
        ff = fonts.script_font()
        fam = None
        if ff:
            fid = QFontDatabase.addApplicationFont(ff)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            fam = fams[0] if fams else None
        f = QFont(fam) if fam else QFont("serif")
        f.setItalic(fam is None)
        f.setPixelSize(40)
        self.preview.setFont(f)
        self.name.textChanged.connect(self.preview.setText)
        self.preview.setText(default_name)
        tl.addWidget(self.name)
        tl.addWidget(self.preview)
        self.tabs.addTab(tw, "Type")
        # draw
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.pad = DrawPad()
        clear = QPushButton("Clear")
        clear.clicked.connect(self.pad.clear)
        dl.addWidget(self.pad)
        dl.addWidget(clear, alignment=Qt.AlignRight)
        self.tabs.addTab(dw, "Draw")
        # image
        iw = QWidget()
        il = QVBoxLayout(iw)
        self.img_path = None
        self.img_label = QLabel("No image chosen")
        self.img_label.setMinimumHeight(100)
        self.img_label.setAlignment(Qt.AlignCenter)
        pick = QPushButton("Choose image…")
        pick.clicked.connect(self._pick)
        il.addWidget(self.img_label)
        il.addWidget(pick, alignment=Qt.AlignRight)
        self.tabs.addTab(iw, "Image")
        v.addWidget(self.tabs)
        self.details = SignerDetails(default_name)
        v.addWidget(self.details)
        self.save = QCheckBox("Save this signature for next time", checked=True)
        v.addWidget(self.save)
        _buttons(self, v)

    def _pick(self):
        p = QFileDialog.getOpenFileName(self, "Signature image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)")[0]
        if p:
            self.img_path = p
            self.img_label.setPixmap(QPixmap(p).scaled(360, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def spec(self) -> dict | None:
        i = self.tabs.currentIndex()
        if i == 0 and self.name.text().strip():
            return {"kind": "typed", "name": self.name.text().strip()}
        if i == 1 and self.pad.strokes:
            return {"kind": "ink", "strokes": self.pad.strokes, "size": (self.pad.width(), self.pad.height())}
        if i == 2 and self.img_path:
            return {"kind": "image", "path": self.img_path}
        return None

    @staticmethod
    def ask(parent, default_name=""):
        d = SignatureDialog(parent, default_name)
        while d.exec() == QDialog.Accepted:
            s = d.spec()
            if s:
                save_signer_profile(d.details.profile())
                if d.save.isChecked():
                    save_signature(s)
                return s
            QMessageBox.information(d, "Signature", "Type a name, draw a signature or choose an image first.")
        return None


def saved_signatures() -> list[dict]:
    try:
        return json.loads(SIGS.read_text())
    except (OSError, ValueError):
        return []


def save_signature(spec: dict):
    sigs = [s for s in saved_signatures() if s != spec][:9]
    SIGS.parent.mkdir(parents=True, exist_ok=True)
    SIGS.write_text(json.dumps([spec] + sigs))


def describe_signature(s: dict) -> str:
    return {"typed": f"Typed: {s.get('name')}", "ink": "Drawn signature",
            "image": f"Image: {os.path.basename(s.get('path', ''))}"}[s["kind"]]


# ---- digital IDs and signing --------------------------------------------------------------------------
class CreateIDDialog(QDialog):
    def __init__(self, parent, name=""):
        super().__init__(parent)
        self.setWindowTitle("Create Digital ID (self-signed)")
        f = QFormLayout(self)
        self.name = QLineEdit(name)
        self.email = QLineEdit()
        self.org = QLineEdit()
        self.pw = QLineEdit(echoMode=QLineEdit.Password)
        self.pw2 = QLineEdit(echoMode=QLineEdit.Password)
        f.addRow("Name:", self.name)
        f.addRow("Email:", self.email)
        f.addRow("Organization:", self.org)
        f.addRow("Password:", self.pw)
        f.addRow("Confirm password:", self.pw2)
        f.addRow(QLabel(f"Saved in {IDS}"))
        _buttons(self, f)

    @staticmethod
    def ask(parent, name=""):
        from ..commands import run
        d = CreateIDDialog(parent, name)
        while d.exec() == QDialog.Accepted:
            if not d.name.text().strip() or not d.pw.text():
                QMessageBox.warning(d, "Digital ID", "Name and password are required.")
                continue
            if d.pw.text() != d.pw2.text():
                QMessageBox.warning(d, "Digital ID", "The passwords do not match.")
                continue
            safe = "".join(c if c.isalnum() else "_" for c in d.name.text().strip())
            path = str(IDS / f"{safe}.pfx")
            n = 2
            while os.path.exists(path):
                path = str(IDS / f"{safe}_{n}.pfx")
                n += 1
            run("Sign.CreateID", path, d.name.text().strip(), d.pw.text(), email=d.email.text() or None,
                org=d.org.text() or None)
            return path
        return None


class DigitalSignDialog(QDialog):
    def __init__(self, parent, certify_default=False, name=""):
        super().__init__(parent)
        self.setWindowTitle("Certify Document" if certify_default else "Sign Document")
        self._name = name
        f = QFormLayout(self)
        row = QHBoxLayout()
        self.ids = QComboBox()
        self._load_ids()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        new = QPushButton("New ID…")
        new.clicked.connect(self._new)
        row.addWidget(self.ids, 1)
        row.addWidget(browse)
        row.addWidget(new)
        f.addRow("Digital ID:", row)
        self.pw = QLineEdit(echoMode=QLineEdit.Password)
        f.addRow("Password:", self.pw)
        self.reason = QLineEdit("I am the author of this document" if certify_default else "I approve this document")
        self.location = QLineEdit()
        f.addRow("Reason:", self.reason)
        f.addRow("Location:", self.location)
        self.kind = QComboBox()
        self.kind.addItems(["Sign", "Certify: no changes allowed", "Certify: form filling and signing",
                            "Certify: form filling, signing and commenting"])
        self.kind.setCurrentIndex(2 if certify_default else 0)
        f.addRow("Type:", self.kind)
        self.invisible = QCheckBox("Invisible signature (no box on the page)")
        f.addRow(self.invisible)
        _buttons(self, f)

    def _load_ids(self, select: str | None = None):
        self.ids.clear()
        for p in sorted(glob.glob(str(IDS / "*.pfx")) + glob.glob(str(IDS / "*.p12"))):
            self.ids.addItem(os.path.basename(p), p)
        last = QSettings("pdfdesk", "pdfdesk").value("last_id")
        for want in (select, last):
            if want:
                i = self.ids.findData(want)
                if i < 0:
                    self.ids.addItem(os.path.basename(want), want)
                    i = self.ids.count() - 1
                self.ids.setCurrentIndex(i)
                break

    def _browse(self):
        p = QFileDialog.getOpenFileName(self, "Digital ID", str(Path.home()), "Digital ID (*.pfx *.p12)")[0]
        if p:
            self._load_ids(p)

    def _new(self):
        p = CreateIDDialog.ask(self, self._name)
        if p:
            self._load_ids(p)

    def values(self) -> dict:
        certify = {0: None, 1: "none", 2: "forms", 3: "annotations"}[self.kind.currentIndex()]
        return {"pfx": self.ids.currentData(), "password": self.pw.text(), "reason": self.reason.text() or None,
                "location": self.location.text() or None, "certify": certify, "invisible": self.invisible.isChecked()}

    @staticmethod
    def ask(parent, certify=False, name=""):
        d = DigitalSignDialog(parent, certify, name)
        while d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["pfx"]:
                QMessageBox.warning(d, "Sign", "Choose or create a digital ID first.")
                continue
            from pyhanko.sign import signers
            try:
                ok = signers.SimpleSigner.load_pkcs12(v["pfx"], passphrase=v["password"].encode()) is not None
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                QMessageBox.warning(d, "Sign", "Could not open the digital ID. Check the password.")
                continue
            QSettings("pdfdesk", "pdfdesk").setValue("last_id", v["pfx"])
            return v
        return None


# ---- security ------------------------------------------------------------------------------------------------
class PasswordDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Password Protect")
        v = QVBoxLayout(self)
        g1 = QGroupBox("Document open")
        f1 = QFormLayout(g1)
        self.require_open = QCheckBox("Require a password to open the document", checked=True)
        self.user = QLineEdit(echoMode=QLineEdit.Password)
        self.user2 = QLineEdit(echoMode=QLineEdit.Password)
        f1.addRow(self.require_open)
        f1.addRow("Open password:", self.user)
        f1.addRow("Confirm:", self.user2)
        self.require_open.toggled.connect(self.user.setEnabled)
        self.require_open.toggled.connect(self.user2.setEnabled)
        v.addWidget(g1)
        g2 = QGroupBox("Permissions")
        f2 = QFormLayout(g2)
        self.owner = QLineEdit(echoMode=QLineEdit.Password)
        self.owner2 = QLineEdit(echoMode=QLineEdit.Password)
        f2.addRow("Permissions password:", self.owner)
        f2.addRow("Confirm:", self.owner2)
        self.p_print = QCheckBox("Allow printing", checked=True)
        self.p_copy = QCheckBox("Allow copying text and images", checked=True)
        self.p_annot = QCheckBox("Allow comments and form filling", checked=True)
        self.p_modify = QCheckBox("Allow changing the document", checked=False)
        for w in (self.p_print, self.p_copy, self.p_annot, self.p_modify):
            f2.addRow(w)
        v.addWidget(g2)
        row = QHBoxLayout()
        row.addWidget(QLabel("Encryption:"))
        self.method = QComboBox()
        self.method.addItems(["AES-256", "AES-128", "RC4-128"])
        row.addWidget(self.method)
        row.addStretch()
        v.addLayout(row)
        _buttons(self, v)

    @staticmethod
    def ask(parent):
        from ..core import security as sec
        d = PasswordDialog(parent)
        while d.exec() == QDialog.Accepted:
            user = d.user.text() if d.require_open.isChecked() else ""
            if d.require_open.isChecked() and (not user or user != d.user2.text()):
                QMessageBox.warning(d, "Password", "Enter the open password twice.")
                continue
            if not d.owner.text() or d.owner.text() != d.owner2.text():
                QMessageBox.warning(d, "Password", "Enter the permissions password twice.")
                continue
            if d.owner.text() == user:
                QMessageBox.warning(d, "Password", "The permissions password must differ from the open password.")
                continue
            return sec.Security(user, d.owner.text(),
                                sec.permissions(d.p_print.isChecked(), d.p_copy.isChecked(), d.p_modify.isChecked(),
                                                d.p_annot.isChecked()),
                                sec.METHODS[d.method.currentText()])
        return None


# ---- page marks ------------------------------------------------------------------------------------------------
class HeaderFooterDialog(QDialog):
    def __init__(self, parent, bates=False):
        super().__init__(parent)
        self.setWindowTitle("Bates Numbering" if bates else "Header & Footer")
        v = QVBoxLayout(self)
        grid = QGridLayout()
        self.fields = {}
        for r, row in enumerate(("Header", "Footer")):
            grid.addWidget(QLabel(row), r * 2, 0)
            for c, col in enumerate(("Left", "Center", "Right")):
                grid.addWidget(QLabel(col), r * 2, c + 1)
                e = QLineEdit()
                self.fields[(row, col)] = e
                grid.addWidget(e, r * 2 + 1, c + 1)
        v.addLayout(grid)
        v.addWidget(QLabel("Macros: <<page>>  <<total>>  <<bates>>"))
        f = QFormLayout()
        self.size = QDoubleSpinBox(minimum=4, maximum=72, value=10)
        self.margin = QDoubleSpinBox(minimum=0, maximum=200, value=36)
        self.pages = QLineEdit(placeholderText="all (e.g. 1-3,7, odd, even)")
        f.addRow("Font size:", self.size)
        f.addRow("Margin (pt):", self.margin)
        f.addRow("Pages:", self.pages)
        v.addLayout(f)
        self.bates_box = QGroupBox("Bates number")
        self.bates_box.setCheckable(True)
        self.bates_box.setChecked(bates)
        bf = QFormLayout(self.bates_box)
        self.prefix = QLineEdit("ABC")
        self.suffix = QLineEdit()
        self.digits = QSpinBox(minimum=3, maximum=15, value=6)
        self.start = QSpinBox(minimum=0, maximum=10**9, value=1)
        self.increment = QSpinBox(minimum=-1000, maximum=1000, value=1)
        bf.addRow("Prefix:", self.prefix)
        bf.addRow("Suffix:", self.suffix)
        bf.addRow("Digits:", self.digits)
        bf.addRow("Start:", self.start)
        bf.addRow("Increment:", self.increment)
        v.addWidget(self.bates_box)
        if bates:
            self.fields[("Footer", "Right")].setText("<<bates>>")
        else:
            self.fields[("Footer", "Center")].setText("Page <<page>> of <<total>>")
        _buttons(self, v)

    def values(self) -> dict:
        get = lambda r, c: self.fields[(r, c)].text()  # noqa: E731
        kw = {"header": tuple(get("Header", c) for c in ("Left", "Center", "Right")),
              "footer": tuple(get("Footer", c) for c in ("Left", "Center", "Right")),
              "fontsize": self.size.value(), "margin": self.margin.value(), "pages": self.pages.text() or None}
        if self.bates_box.isChecked():
            kw["bates"] = {"prefix": self.prefix.text(), "suffix": self.suffix.text(), "digits": self.digits.value(),
                           "start": self.start.value(), "increment": self.increment.value()}
        return kw


class WatermarkDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add Watermark")
        f = QFormLayout(self)
        self.text = QLineEdit("CONFIDENTIAL")
        self.size = QDoubleSpinBox(minimum=6, maximum=300, value=60)
        self.rot = QDoubleSpinBox(minimum=-180, maximum=180, value=45)
        self.opacity = QDoubleSpinBox(minimum=0.05, maximum=1, singleStep=0.05, value=0.3)
        self.behind = QCheckBox("Behind page content")
        self.pages = QLineEdit(placeholderText="all")
        f.addRow("Text:", self.text)
        f.addRow("Font size:", self.size)
        f.addRow("Rotation:", self.rot)
        f.addRow("Opacity:", self.opacity)
        f.addRow(self.behind)
        f.addRow("Pages:", self.pages)
        _buttons(self, f)

    def values(self):
        return {"text": self.text.text(), "fontsize": self.size.value(), "rotate": self.rot.value(),
                "opacity": self.opacity.value(), "behind": self.behind.isChecked(), "pages": self.pages.text() or None}


class PropertiesDialog(QDialog):
    def __init__(self, parent, doc, path):
        super().__init__(parent)
        self.setWindowTitle("Document Properties")
        f = QFormLayout(self)
        m = doc.metadata or {}
        self.edits = {}
        for key in ("title", "author", "subject", "keywords"):
            e = QLineEdit(m.get(key, "") or "")
            self.edits[key] = e
            f.addRow(key.capitalize() + ":", e)
        info = [("File", path or "(not saved)"), ("Pages", str(doc.page_count)),
                ("Page size", f"{doc[0].rect.width:.0f} × {doc[0].rect.height:.0f} pt" if doc.page_count else ""),
                ("Producer", m.get("producer", "")), ("Creator", m.get("creator", "")),
                ("PDF format", m.get("format", "")), ("Encryption", m.get("encryption") or "none"),
                ("Fonts", ", ".join(sorted({f[3].split('+')[-1] for p in doc.pages(0, min(doc.page_count, 30))
                                            for f in p.get_fonts()}))[:300])]
        for k, val in info:
            lab = QLabel(val)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(k + ":", lab)
        _buttons(self, f)

    def values(self):
        return {k: e.text() for k, e in self.edits.items()}


class SplitDialog(QDialog):
    def __init__(self, parent, has_bookmarks: bool):
        super().__init__(parent)
        self.setWindowTitle("Split Document")
        f = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItems(["Every N pages", "Top-level bookmarks"])
        if not has_bookmarks:
            self.mode.model().item(1).setEnabled(False)
        self.n = QSpinBox(minimum=1, maximum=100000, value=1)
        f.addRow("Split by:", self.mode)
        f.addRow("Pages per file:", self.n)
        _buttons(self, f)

    def values(self):
        return {"by_bookmarks": self.mode.currentIndex() == 1, "every": self.n.value()}


class LayersDialog(QDialog):
    """Show or hide optional-content layers."""
    def __init__(self, parent, layers: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("Layers")
        lay = QVBoxLayout(self)
        self.boxes = []
        if not layers:
            lay.addWidget(QLabel("This document has no layers."))
        for ly in layers:
            b = QCheckBox(ly["name"])
            b.setChecked(ly["on"])
            b.setProperty("xref", ly["xref"])
            lay.addWidget(b)
            self.boxes.append(b)
        _buttons(self, lay)

    def values(self) -> dict[int, bool]:
        return {b.property("xref"): b.isChecked() for b in self.boxes}


class FolderSearchDialog(QDialog):
    """Advanced Search over every PDF in a folder; double-click a hit to open it at that page."""
    def __init__(self, parent, open_hit):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self._item = QListWidgetItem
        self.setWindowTitle("Advanced Search")
        self.resize(720, 480)
        self.open_hit = open_hit
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.text = QLineEdit()
        row = QHBoxLayout()
        self.folder = QLineEdit(str(Path.home() / "Documents"))
        pick = QPushButton("Browse…")
        pick.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "Folder", self.folder.text()))
                             and self.folder.setText(d))
        row.addWidget(self.folder)
        row.addWidget(pick)
        f.addRow("Find:", self.text)
        f.addRow("In folder:", row)
        opts = QHBoxLayout()
        self.sub, self.word, self.case = QCheckBox("Include subfolders"), QCheckBox("Whole words"), QCheckBox("Match case")
        self.sub.setChecked(True)
        for b in (self.sub, self.word, self.case):
            opts.addWidget(b)
        f.addRow("", opts)
        lay.addLayout(f)
        go = QPushButton("Search")
        go.setDefault(True)
        go.clicked.connect(self.search)
        self.text.returnPressed.connect(self.search)
        lay.addWidget(go)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda it: it.data(Qt.UserRole) and self.open_hit(*it.data(Qt.UserRole)))
        lay.addWidget(self.results)

    def search(self):
        from ..commands import run
        t = self.text.text().strip()
        if not t or not os.path.isdir(self.folder.text()):
            self.status.setText("Enter text and an existing folder.")
            return
        self.status.setText("Searching…")
        self.repaint()
        hits = run("Search.Folder", self.folder.text(), t, recursive=self.sub.isChecked(),
                   whole_word=self.word.isChecked(), case=self.case.isChecked())
        self.results.clear()
        files = set()
        for h in hits:
            where = f"p.{h['page']}" if h["page"] else ""
            it = self._item(f"{os.path.basename(h['path'])}  {where}   {h['context']}")
            it.setToolTip(h["path"])
            if h["page"]:
                it.setData(Qt.UserRole, (h["path"], h["page"]))
                files.add(h["path"])
            self.results.addItem(it)
        self.status.setText(f"{sum(1 for h in hits if h['page'])} matches in {len(files)} file(s)")
