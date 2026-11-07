"""Dialogs for the ribbon commands."""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QSettings, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import fonts
from ..lang import tr

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
            row.addWidget(QLabel(tr("Font size:")))
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


# ---- colors and comment properties --------------------------------------------------------------------
PRESET_COLORS = [("Yellow", (1, 0.85, 0)), ("Green", (0.3, 0.85, 0.3)), ("Cyan", (0.3, 0.8, 1)),
                 ("Pink", (1, 0.45, 0.75)), ("Orange", (1, 0.6, 0.1)), ("Red", (0.9, 0.1, 0.1)),
                 ("Blue", (0.1, 0.3, 0.9)), ("Purple", (0.55, 0.25, 0.85)), ("Gray", (0.5, 0.5, 0.5)),
                 ("Black", (0, 0, 0)), ("White", (1, 1, 1))]


def qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*rgb) if rgb else QColor(0, 0, 0, 0)


def swatch(rgb, size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QColor(110, 110, 110))
    p.setBrush(qcolor(rgb) if rgb else Qt.NoBrush)
    p.drawRect(0, 0, size - 1, size - 1)
    if not rgb:                                                 # "no color": a red slash
        p.setPen(QPen(QColor(220, 30, 30), 1.5))
        p.drawLine(1, size - 2, size - 2, 1)
    p.end()
    return QIcon(pm)


def fill_color_menu(m: QMenu, pick, current=None, none_label: str | None = None):
    """Preset swatches, "More colors…" and optionally a "no color" entry; pick(rgb or None) on choice."""
    if none_label:
        m.addAction(swatch(None), none_label, lambda: pick(None))
    for name, rgb in PRESET_COLORS:
        m.addAction(swatch(rgb), name, lambda c=rgb: pick(c))

    def more():
        c = QColorDialog.getColor(qcolor(current) if current else QColor(255, 220, 0), m.parentWidget(), "Color")
        if c.isValid():
            pick((c.redF(), c.greenF(), c.blueF()))
    m.addAction(tr("More colors…"), more)


class ColorButton(QToolButton):
    """A swatch that opens the color menu."""
    changed = Signal(object)            # rgb tuple, or None for "no color"

    def __init__(self, rgb=None, none_label: str | None = None, text: str = ""):
        super().__init__()
        self.rgb = rgb
        self.setPopupMode(QToolButton.InstantPopup)
        if text:
            self.setText(text)
            self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        m = QMenu(self)
        m.aboutToShow.connect(lambda: (m.clear(), fill_color_menu(m, self.set_color, self.rgb, none_label)))
        self.setMenu(m)
        self._show()

    def set_color(self, rgb, emit: bool = True):
        self.rgb = tuple(rgb) if rgb else None
        self._show()
        if emit:
            self.changed.emit(self.rgb)

    def _show(self):
        self.setIcon(swatch(self.rgb, 18))


class CommentPropertiesDialog(QDialog):
    """Text and appearance of one comment; shows only what that kind of comment has (Comment.Style fields)."""

    def __init__(self, parent, st: dict):
        super().__init__(parent)
        self.st = st
        self.setWindowTitle(f"{st['type']} properties")
        v = QVBoxLayout(self)
        f = QFormLayout()
        fields = st["fields"]
        self.text = QPlainTextEdit(st["content"])
        self.text.setMinimumSize(360, 90)
        f.addRow("Text:" if st["type"] == "FreeText" else "Comment:", self.text)
        self.color = self.text_color = self.fill = self.width = self.size = None
        if "color" in fields:
            self.color = ColorButton(st["color"])
            f.addRow(tr("Color:"), self.color)
        if "text_color" in fields:
            self.text_color = ColorButton(st["text_color"])
            f.addRow(tr("Text color:"), self.text_color)
        if "fontsize" in fields:
            self.size = QDoubleSpinBox(minimum=4, maximum=144, value=st["fontsize"], decimals=1)
            f.addRow(tr("Font size:"), self.size)
        if "fill" in fields:
            self.fill = ColorButton(st["fill"], none_label="No fill")
            f.addRow(tr("Fill:"), self.fill)
        if "width" in fields:
            self.width = QDoubleSpinBox(minimum=0, maximum=20, value=st["width"], singleStep=0.5, decimals=1)
            f.addRow(tr("Line width:"), self.width)
        self.opacity = QSpinBox(minimum=5, maximum=100, value=round(st["opacity"] * 100), suffix=" %")
        f.addRow(tr("Opacity:"), self.opacity)
        v.addLayout(f)
        _buttons(self, v)

    def changes(self) -> dict:
        """Only what was changed, as Comment.SetStyle keyword arguments."""
        st, out = self.st, {}
        text = self.text.toPlainText().rstrip("\n")
        if text != st["content"]:
            out["text"] = text
        for key, w in (("color", self.color), ("text_color", self.text_color), ("fill", self.fill)):
            if w is not None and not _same(w.rgb, st.get(key)):
                out[key] = w.rgb
        for key, w in (("fontsize", self.size), ("width", self.width)):
            if w is not None and abs(w.value() - st[key]) > 1e-3:
                out[key] = w.value()
        if self.opacity.value() != round(st["opacity"] * 100):
            out["opacity"] = self.opacity.value() / 100
        return out

    @staticmethod
    def ask(parent, st: dict) -> dict | None:
        d = CommentPropertiesDialog(parent, st)
        d.text.setFocus()
        return d.changes() if d.exec() == QDialog.Accepted else None


def _same(a, b) -> bool:
    if not a or not b:
        return not a and not b
    return all(abs(x - y) < 2 / 255 for x, y in zip(a, b))


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
        super().__init__(tr("Details under the signature"))
        prof = signer_profile()
        prof.setdefault("name", default_name)
        show = set(prof.get("show", ()))
        g = QGridLayout(self)
        self.checks, self.edits = {}, {}
        for i, (k, label) in enumerate(self.LABELS.items()):
            self.checks[k] = QCheckBox(tr(label), checked=k in show)
            g.addWidget(self.checks[k], i, 0)
            if k != "date":
                self.edits[k] = QLineEdit(prof.get(k, ""))
                self.edits[k].textEdited.connect(lambda _t, c=self.checks[k]: c.setChecked(True))
                g.addWidget(self.edits[k], i, 1)
        self.layout_box = QComboBox()
        self.layout_box.addItem(tr("One detail per line"), "lines")
        self.layout_box.addItem(tr("Compact: two lines"), "compact")
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(prof.get("layout", "lines"))))
        g.addWidget(QLabel(tr("Layout")), len(self.LABELS), 0)
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
        self.setWindowTitle(tr("Signer Details"))
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
        self.setWindowTitle(tr("Create Signature"))
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # type
        tw = QWidget()
        tl = QVBoxLayout(tw)
        self.name = QLineEdit(default_name, placeholderText=tr("Your name"))
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
        self.tabs.addTab(tw, tr("Type"))
        # draw
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.pad = DrawPad()
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self.pad.clear)
        dl.addWidget(self.pad)
        dl.addWidget(clear, alignment=Qt.AlignRight)
        self.tabs.addTab(dw, tr("Draw"))
        # image
        iw = QWidget()
        il = QVBoxLayout(iw)
        self.img_path = None
        self.img_label = QLabel(tr("No image chosen"))
        self.img_label.setMinimumHeight(100)
        self.img_label.setAlignment(Qt.AlignCenter)
        pick = QPushButton(tr("Choose image…"))
        pick.clicked.connect(self._pick)
        il.addWidget(self.img_label)
        il.addWidget(pick, alignment=Qt.AlignRight)
        self.tabs.addTab(iw, tr("Image"))
        v.addWidget(self.tabs)
        self.details = SignerDetails(default_name)
        v.addWidget(self.details)
        self.save = QCheckBox(tr("Save this signature for next time"), checked=True)
        v.addWidget(self.save)
        _buttons(self, v)

    def _pick(self):
        p = QFileDialog.getOpenFileName(self, tr("Signature image"), "", tr("Images (*.png *.jpg *.jpeg *.bmp *.gif)"))[0]
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
            QMessageBox.information(d, tr("Signature"), tr("Type a name, draw a signature or choose an image first."))
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
    return {"typed": tr("Typed: {name}", name=s.get("name")), "ink": tr("Drawn signature"),
            "image": tr("Image: {name}", name=os.path.basename(s.get("path", "")))}[s["kind"]]


# ---- digital IDs and signing --------------------------------------------------------------------------
class CreateIDDialog(QDialog):
    def __init__(self, parent, name=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Create Digital ID (self-signed)"))
        f = QFormLayout(self)
        self.name = QLineEdit(name)
        self.email = QLineEdit()
        self.org = QLineEdit()
        self.pw = QLineEdit(echoMode=QLineEdit.Password)
        self.pw2 = QLineEdit(echoMode=QLineEdit.Password)
        f.addRow(tr("Name:"), self.name)
        f.addRow(tr("Email:"), self.email)
        f.addRow(tr("Organization:"), self.org)
        f.addRow(tr("Password:"), self.pw)
        f.addRow(tr("Confirm password:"), self.pw2)
        f.addRow(QLabel(tr("Saved in {path}", path=IDS)))
        _buttons(self, f)

    @staticmethod
    def ask(parent, name=""):
        from ..commands import run
        d = CreateIDDialog(parent, name)
        while d.exec() == QDialog.Accepted:
            if not d.name.text().strip() or not d.pw.text():
                QMessageBox.warning(d, tr("Digital ID"), tr("Name and password are required."))
                continue
            if d.pw.text() != d.pw2.text():
                QMessageBox.warning(d, tr("Digital ID"), tr("The passwords do not match."))
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
        self.setWindowTitle(tr("Certify Document") if certify_default else tr("Sign Document"))
        self._name = name
        f = QFormLayout(self)
        row = QHBoxLayout()
        self.ids = QComboBox()
        self._load_ids()
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._browse)
        new = QPushButton(tr("New ID…"))
        new.clicked.connect(self._new)
        row.addWidget(self.ids, 1)
        row.addWidget(browse)
        row.addWidget(new)
        f.addRow(tr("Digital ID:"), row)
        self.pw = QLineEdit(echoMode=QLineEdit.Password)
        f.addRow(tr("Password:"), self.pw)
        self.reason = QLineEdit(tr("I am the author of this document") if certify_default else tr("I approve this document"))
        self.location = QLineEdit()
        f.addRow(tr("Reason:"), self.reason)
        f.addRow(tr("Location:"), self.location)
        self.kind = QComboBox()
        self.kind.addItems([tr(s) for s in ("Sign", "Certify: no changes allowed", "Certify: form filling and signing",
                                            "Certify: form filling, signing and commenting")])
        self.kind.setCurrentIndex(2 if certify_default else 0)
        f.addRow(tr("Type:"), self.kind)
        self.invisible = QCheckBox(tr("Invisible signature (no box on the page)"))
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
        p = QFileDialog.getOpenFileName(self, tr("Digital ID"), str(Path.home()), tr("Digital ID (*.pfx *.p12)"))[0]
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
                QMessageBox.warning(d, tr("Sign"), tr("Choose or create a digital ID first."))
                continue
            from pyhanko.sign import signers
            try:
                ok = signers.SimpleSigner.load_pkcs12(v["pfx"], passphrase=v["password"].encode()) is not None
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                QMessageBox.warning(d, tr("Sign"), tr("Could not open the digital ID. Check the password."))
                continue
            QSettings("pdfdesk", "pdfdesk").setValue("last_id", v["pfx"])
            return v
        return None


# ---- security ------------------------------------------------------------------------------------------------
class PasswordDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("Password Protect"))
        v = QVBoxLayout(self)
        g1 = QGroupBox(tr("Document open"))
        f1 = QFormLayout(g1)
        self.require_open = QCheckBox(tr("Require a password to open the document"), checked=True)
        self.user = QLineEdit(echoMode=QLineEdit.Password)
        self.user2 = QLineEdit(echoMode=QLineEdit.Password)
        f1.addRow(self.require_open)
        f1.addRow(tr("Open password:"), self.user)
        f1.addRow(tr("Confirm:"), self.user2)
        self.require_open.toggled.connect(self.user.setEnabled)
        self.require_open.toggled.connect(self.user2.setEnabled)
        v.addWidget(g1)
        g2 = QGroupBox(tr("Permissions"))
        f2 = QFormLayout(g2)
        self.owner = QLineEdit(echoMode=QLineEdit.Password)
        self.owner2 = QLineEdit(echoMode=QLineEdit.Password)
        f2.addRow(tr("Permissions password:"), self.owner)
        f2.addRow(tr("Confirm:"), self.owner2)
        self.p_print = QCheckBox(tr("Allow printing"), checked=True)
        self.p_copy = QCheckBox(tr("Allow copying text and images"), checked=True)
        self.p_annot = QCheckBox(tr("Allow comments and form filling"), checked=True)
        self.p_modify = QCheckBox(tr("Allow changing the document"), checked=False)
        for w in (self.p_print, self.p_copy, self.p_annot, self.p_modify):
            f2.addRow(w)
        v.addWidget(g2)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Encryption:")))
        self.method = QComboBox()
        self.method.addItems([tr(s) for s in ("AES-256", "AES-128", "RC4-128")])
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
                QMessageBox.warning(d, tr("Password"), tr("Enter the open password twice."))
                continue
            if not d.owner.text() or d.owner.text() != d.owner2.text():
                QMessageBox.warning(d, tr("Password"), tr("Enter the permissions password twice."))
                continue
            if d.owner.text() == user:
                QMessageBox.warning(d, tr("Password"), tr("The permissions password must differ from the open password."))
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
        self.setWindowTitle(tr("Bates Numbering") if bates else tr("Header & Footer"))
        v = QVBoxLayout(self)
        grid = QGridLayout()
        self.fields = {}
        for r, row in enumerate(("Header", "Footer")):
            grid.addWidget(QLabel(tr(row)), r * 2, 0)
            for c, col in enumerate(("Left", "Center", "Right")):
                grid.addWidget(QLabel(tr(col)), r * 2, c + 1)
                e = QLineEdit()
                self.fields[(row, col)] = e
                grid.addWidget(e, r * 2 + 1, c + 1)
        v.addLayout(grid)
        v.addWidget(QLabel(tr("Macros: <<page>>  <<total>>  <<bates>>")))
        f = QFormLayout()
        self.size = QDoubleSpinBox(minimum=4, maximum=72, value=10)
        self.margin = QDoubleSpinBox(minimum=0, maximum=200, value=36)
        self.pages = QLineEdit(placeholderText=tr("all (e.g. 1-3,7, odd, even)"))
        f.addRow(tr("Font size:"), self.size)
        f.addRow(tr("Margin (pt):"), self.margin)
        f.addRow(tr("Pages:"), self.pages)
        v.addLayout(f)
        self.bates_box = QGroupBox(tr("Bates number"))
        self.bates_box.setCheckable(True)
        self.bates_box.setChecked(bates)
        bf = QFormLayout(self.bates_box)
        self.prefix = QLineEdit("ABC")
        self.suffix = QLineEdit()
        self.digits = QSpinBox(minimum=3, maximum=15, value=6)
        self.start = QSpinBox(minimum=0, maximum=10**9, value=1)
        self.increment = QSpinBox(minimum=-1000, maximum=1000, value=1)
        bf.addRow(tr("Prefix:"), self.prefix)
        bf.addRow(tr("Suffix:"), self.suffix)
        bf.addRow(tr("Digits:"), self.digits)
        bf.addRow(tr("Start:"), self.start)
        bf.addRow(tr("Increment:"), self.increment)
        v.addWidget(self.bates_box)
        if bates:
            self.fields[("Footer", "Right")].setText("<<bates>>")
        else:
            self.fields[("Footer", "Center")].setText(tr("Page <<page>> of <<total>>"))
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
        self.setWindowTitle(tr("Add Watermark"))
        f = QFormLayout(self)
        self.text = QLineEdit(tr("CONFIDENTIAL"))
        self.size = QDoubleSpinBox(minimum=6, maximum=300, value=60)
        self.rot = QDoubleSpinBox(minimum=-180, maximum=180, value=45)
        self.opacity = QDoubleSpinBox(minimum=0.05, maximum=1, singleStep=0.05, value=0.3)
        self.behind = QCheckBox(tr("Behind page content"))
        self.pages = QLineEdit(placeholderText=tr("all"))
        f.addRow(tr("Text:"), self.text)
        f.addRow(tr("Font size:"), self.size)
        f.addRow(tr("Rotation:"), self.rot)
        f.addRow(tr("Opacity:"), self.opacity)
        f.addRow(self.behind)
        f.addRow(tr("Pages:"), self.pages)
        _buttons(self, f)

    def values(self):
        return {"text": self.text.text(), "fontsize": self.size.value(), "rotate": self.rot.value(),
                "opacity": self.opacity.value(), "behind": self.behind.isChecked(), "pages": self.pages.text() or None}


class PropertiesDialog(QDialog):
    def __init__(self, parent, doc, path):
        super().__init__(parent)
        self.setWindowTitle(tr("Document Properties"))
        f = QFormLayout(self)
        m = doc.metadata or {}
        self.edits = {}
        for key, label in (("title", "Title"), ("author", "Author"), ("subject", "Subject"), ("keywords", "Keywords")):
            e = QLineEdit(m.get(key, "") or "")
            self.edits[key] = e
            f.addRow(tr(label) + ":", e)
        info = [("File", path or tr("(not saved)")), ("Pages", str(doc.page_count)),
                ("Page size", f"{doc[0].rect.width:.0f} × {doc[0].rect.height:.0f} pt" if doc.page_count else ""),
                ("Producer", m.get("producer", "")), ("Creator", m.get("creator", "")),
                ("PDF format", m.get("format", "")), ("Encryption", m.get("encryption") or tr("none")),
                ("Fonts", ", ".join(sorted({f[3].split('+')[-1] for p in doc.pages(0, min(doc.page_count, 30))
                                            for f in p.get_fonts()}))[:300])]
        for k, val in info:
            lab = QLabel(val)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(tr(k) + ":", lab)
        _buttons(self, f)

    def values(self):
        return {k: e.text() for k, e in self.edits.items()}


class SplitDialog(QDialog):
    def __init__(self, parent, has_bookmarks: bool):
        super().__init__(parent)
        self.setWindowTitle(tr("Split Document"))
        f = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItems([tr(s) for s in ("Every N pages", "Top-level bookmarks")])
        if not has_bookmarks:
            self.mode.model().item(1).setEnabled(False)
        self.n = QSpinBox(minimum=1, maximum=100000, value=1)
        f.addRow(tr("Split by:"), self.mode)
        f.addRow(tr("Pages per file:"), self.n)
        _buttons(self, f)

    def values(self):
        return {"by_bookmarks": self.mode.currentIndex() == 1, "every": self.n.value()}


class LayersDialog(QDialog):
    """Show or hide optional-content layers."""
    def __init__(self, parent, layers: list[dict]):
        super().__init__(parent)
        self.setWindowTitle(tr("Layers"))
        lay = QVBoxLayout(self)
        self.boxes = []
        if not layers:
            lay.addWidget(QLabel(tr("This document has no layers.")))
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
        self.setWindowTitle(tr("Advanced Search"))
        self.resize(720, 480)
        self.open_hit = open_hit
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.text = QLineEdit()
        row = QHBoxLayout()
        self.folder = QLineEdit(str(Path.home() / "Documents"))
        pick = QPushButton(tr("Browse…"))
        pick.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, tr("Folder"), self.folder.text()))
                             and self.folder.setText(d))
        row.addWidget(self.folder)
        row.addWidget(pick)
        f.addRow(tr("Find:"), self.text)
        f.addRow(tr("In folder:"), row)
        opts = QHBoxLayout()
        self.sub, self.word, self.case = QCheckBox(tr("Include subfolders")), QCheckBox(tr("Whole words")), QCheckBox(tr("Match case"))
        self.sub.setChecked(True)
        for b in (self.sub, self.word, self.case):
            opts.addWidget(b)
        f.addRow("", opts)
        lay.addLayout(f)
        go = QPushButton(tr("Search"))
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
            self.status.setText(tr("Enter text and an existing folder."))
            return
        self.status.setText(tr("Searching…"))
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
        self.status.setText(tr("{n} matches in {files} file(s)", n=sum(1 for h in hits if h["page"]), files=len(files)))


# ---- object position and size ------------------------------------------------------------------------------
class GeometryDialog(QDialog):
    """Position and size of a page object in millimetres from the page's top-left corner."""
    MM = 72 / 25.4

    def __init__(self, parent, rect):
        super().__init__(parent)
        self.setWindowTitle(tr("Position & Size"))
        self.ratio = rect.width / rect.height if rect.height else 1
        f = QFormLayout(self)
        self.x, self.y, self.w, self.h = (QDoubleSpinBox(decimals=1, minimum=-2000, maximum=5000, suffix=" mm")
                                          for _ in range(4))
        for sb, v in ((self.x, rect.x0), (self.y, rect.y0), (self.w, rect.width), (self.h, rect.height)):
            sb.setValue(v / self.MM)
        self.keep = QCheckBox(tr("Keep proportions"), checked=True)
        self.w.valueChanged.connect(lambda v: self.keep.isChecked() and self._sync(self.h, v / self.ratio))
        self.h.valueChanged.connect(lambda v: self.keep.isChecked() and self._sync(self.w, v * self.ratio))
        for label, w in (("Left:", self.x), ("Top:", self.y), ("Width:", self.w), ("Height:", self.h)):
            f.addRow(tr(label), w)
        f.addRow("", self.keep)
        _buttons(self, f)

    @staticmethod
    def _sync(sb, v):
        sb.blockSignals(True)
        sb.setValue(v)
        sb.blockSignals(False)

    @staticmethod
    def ask(parent, rect):
        import pymupdf
        d = GeometryDialog(parent, rect)
        if d.exec() != QDialog.Accepted:
            return None
        m = GeometryDialog.MM
        x, y = d.x.value() * m, d.y.value() * m
        return pymupdf.Rect(x, y, x + max(d.w.value(), 0.5) * m, y + max(d.h.value(), 0.5) * m)


# ---- automatic redaction ----------------------------------------------------------------------------------
class AutoRedactDialog(QDialog):
    """Find personal data in the whole document and pick what to mark. Scanned pages are read with OCR when
    asked, so the hits are blacked out of the image as well."""

    def __init__(self, parent, kinds: list[str], find, has_scans: bool):
        super().__init__(parent)
        from PySide6.QtWidgets import QProgressBar, QTreeWidget, QTreeWidgetItem
        self._item = QTreeWidgetItem
        self.find = find                     # find(kinds, ocr_scans, languages, progress) -> items
        self.items: list[dict] = []
        self.apply_now = False
        self.setWindowTitle(tr("Auto Redact"))
        self.resize(760, 560)
        v = QVBoxLayout(self)
        box = QGroupBox(tr("Look for"))
        g = QGridLayout(box)
        self.kinds = {}
        for n, k in enumerate(kinds):
            self.kinds[k] = QCheckBox(tr(k), checked=True)
            g.addWidget(self.kinds[k], n // 3, n % 3)
        v.addWidget(box)
        row = QHBoxLayout()
        self.ocr = QCheckBox(tr("Also read scanned pages (OCR)"), checked=has_scans)
        from .. import lang
        self.langs = QLineEdit(lang.ocr_languages())
        self.langs.setFixedWidth(110)
        self.langs.setToolTip(tr("OCR languages, e.g. en, de, ar+en"))
        row.addWidget(self.ocr)
        row.addWidget(QLabel(tr("Languages:")))
        row.addWidget(self.langs)
        row.addStretch(1)
        self.go = QPushButton(tr("Find"))
        self.go.setDefault(True)
        self.go.clicked.connect(self.search)
        row.addWidget(self.go)
        v.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Found"), tr("Page")])
        self.tree.setColumnWidth(0, 560)
        v.addWidget(self.tree, 1)
        self.status = QLabel(tr("Press Find to search the document."))
        v.addWidget(self.status)
        bb = QDialogButtonBox()
        self.mark = bb.addButton(tr("Mark selected"), QDialogButtonBox.AcceptRole)
        self.mark_apply = bb.addButton(tr("Mark and apply"), QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        self.mark_apply.clicked.connect(lambda: setattr(self, "apply_now", True))
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        for b in (self.mark, self.mark_apply):
            b.setEnabled(False)
        v.addWidget(bb)

    def search(self):
        from PySide6.QtWidgets import QApplication
        kinds = [k for k, c in self.kinds.items() if c.isChecked()]
        langs = [x for x in self.langs.text().replace(",", "+").split("+") if x.strip()] or ["en"]
        self.go.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText(tr("Searching…"))

        def progress(n, total):
            self.progress.setMaximum(total)
            self.progress.setValue(n)
            QApplication.processEvents()
        try:
            found = self.find(kinds, self.ocr.isChecked(), langs, progress)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, tr("Auto Redact"), str(e))
            found = []
        self.go.setEnabled(True)
        self.progress.setVisible(False)
        self._found = found
        self.tree.clear()
        groups = {}
        for n, it in enumerate(found):
            parent = groups.get(it["kind"])
            if parent is None:
                parent = groups[it["kind"]] = self._item(self.tree, [tr(it["kind"])])
                parent.setFlags(parent.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                parent.setExpanded(True)
            row = self._item(parent, [it["text"] + ("  (" + tr("scan") + ")" if it["scanned"] else ""), str(it["page"])])
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked)
            row.setData(0, Qt.UserRole, n)
        for p in groups.values():
            p.setCheckState(0, Qt.Checked)
        self.status.setText(tr("{n} item(s) found. Untick what should stay.", n=len(found)) if found
                            else tr("Nothing found."))
        for b in (self.mark, self.mark_apply):
            b.setEnabled(bool(found))

    def _accept(self):
        self.items = []
        for g in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(g)
            for r in range(parent.childCount()):
                row = parent.child(r)
                if row.checkState(0) == Qt.Checked:
                    self.items.append(self._found[row.data(0, Qt.UserRole)])
        self.accept()


# ---- combine files ---------------------------------------------------------------------------------------
class CombineDialog(QDialog):
    """The files to combine, in order: drag to reorder, or use the buttons. Each file becomes one bookmark."""

    def __init__(self, parent, paths: list[str]):
        super().__init__(parent)
        from PySide6.QtWidgets import QAbstractItemView, QListWidget
        self.setWindowTitle(tr("Combine Files"))
        self.resize(620, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(tr("The files are combined in this order. Drag them to change it.")))
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        for text, fn in ((tr("Add Files…"), self.add), (tr("Remove"), self.remove), (tr("Move Up"), lambda: self.move(-1)),
                         (tr("Move Down"), lambda: self.move(1)), (tr("Sort by Name"), self.sort)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch(1)
        row.addLayout(side)
        v.addLayout(row)
        self.bb = _buttons(self, v)
        self.bb.button(QDialogButtonBox.Ok).setText(tr("Combine"))
        self.list.model().rowsInserted.connect(self._update)
        self.list.model().rowsRemoved.connect(self._update)
        self._add_paths(paths)
        self._update()

    def _add_paths(self, paths):
        from PySide6.QtWidgets import QListWidgetItem
        have = set(self.files())
        for p in paths:
            if p not in have:
                it = QListWidgetItem(os.path.basename(p))
                it.setToolTip(p)
                it.setData(Qt.UserRole, p)
                self.list.addItem(it)
                have.add(p)

    def files(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def add(self):
        from ..commands.convert import SUPPORTED
        pattern = " ".join("*" + e for e in sorted(SUPPORTED))
        ps = QFileDialog.getOpenFileNames(self, tr("Add Files…"), "", f"{tr('All supported files')} ({pattern})")[0]
        self._add_paths(ps)

    def remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def move(self, step: int):
        rows = sorted((self.list.row(it) for it in self.list.selectedItems()), reverse=step > 0)
        for r in rows:
            to = r + step
            if 0 <= to < self.list.count():
                self.list.insertItem(to, self.list.takeItem(r))
                self.list.item(to).setSelected(True)

    def sort(self):
        paths = sorted(self.files(), key=lambda p: os.path.basename(p).lower())
        self.list.clear()
        self._add_paths(paths)

    def _update(self, *_):
        self.bb.button(QDialogButtonBox.Ok).setEnabled(self.list.count() >= 1)

    @staticmethod
    def ask(parent, paths: list[str]) -> list[str] | None:
        d = CombineDialog(parent, paths)
        if not paths:
            d.add()
        return d.files() if d.exec() == QDialog.Accepted and d.files() else None
