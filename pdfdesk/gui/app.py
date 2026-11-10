"""Main window laid out like Foxit PhantomPDF: ribbon (File tab, tabs, Tell me, Find), quick access toolbar,
Start page and document tabs, navigation pane with an icon strip, bottom bar with page navigation and zoom."""
from __future__ import annotations

import getpass
import glob
import os
import subprocess
import sys
import tempfile

import pymupdf
from PySide6.QtCore import QByteArray, QLocale, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import lang
from ..commands import comment as comment_cmds
from ..commands import invoice as invoice_cmds
from ..commands import run
from ..commands.protect import PATTERNS
from ..core import security as sec
from ..lang import tr
from . import clipboard, dialogs, prefs, theme
from .icons import app_icon, icon
from .panels import Bookmarks, Comments, Thumbnails
from .ribbon import Ribbon
from .start import StartPage, add_recent
from .viewer import DocView

RIBBON = ["File", "Home", "Convert", "Edit", "Fill & Sign", "Organize", "Comment", "View", "Form",
          "Protect", "Invoice", "Share", "Connect", "Accessibility", "Help"]
NOT_YET = {"Share": "Email, shared review and cloud drives are planned for a later phase.",
           "Connect": "Connected services are planned for a later phase.",
           "Accessibility": "Accessibility check and tagging are planned for a later phase."}

TOOL_HINTS = {
    "hand": "Hand: drag to scroll; click a comment or something you added (text, image, signature) to select it, "
            "drag to move (also onto another page), drag a corner to resize; Ctrl+C / Ctrl+V copy and paste, "
            "Delete removes it, double-click or right-click for its properties",
    "select": "Select: drag over text; right-click to highlight, Ctrl+C copies", "zoom": "Zoom: click to zoom in, Shift+click out",
    "highlight": "Highlight: drag across text", "underline": "Underline: drag across text",
    "strikeout": "Strikeout: drag across text", "squiggly": "Squiggly: drag across text",
    "replace-text": "Replace text: drag across the text to replace", "area-highlight": "Area highlight: drag",
    "note": "Note: click and type the note; click elsewhere or Esc to finish", "file": "File attachment: click where it goes",
    "typewriter": "Typewriter: click and type; Enter starts a new line, click elsewhere or Esc to finish",
    "textbox": "Text box: drag a box (or click), then type; click elsewhere or Esc to finish",
    "callout": "Callout: drag from the point to where the box goes, then type",
    "rectangle": "Rectangle: drag", "oval": "Oval: drag", "line": "Line: drag", "arrow": "Arrow: drag",
    "polygon": "Polygon: click points, double-click or Enter to finish",
    "cloud": "Cloud: click points, double-click or Enter to finish",
    "polyline": "Polyline: click points, double-click or Enter to finish",
    "pencil": "Pencil: draw, press Enter to finish", "stamp": "Stamp: drag a box",
    "edit-text": "Edit text: click a line of text and change it, its size or its color; click elsewhere or press Enter to keep it",
    "edit-object": "Edit object: click text, a shape, an image or a signature; drag to move (also onto another page), "
                   "drag a corner to resize, Ctrl+C / Ctrl+V copy and paste, Delete removes it",
    "add-text": "Add text: click and type; Enter starts a new line, click elsewhere or Esc to finish",
    "image": "Add image: drag a box",
    "redact": "Mark for redaction: drag over text or images", "whiteout": "Whiteout: drag over what to erase",
    "sign-place": "Place signature: click or drag a box", "digital-sign": "Digital signature: drag a box",
}
STAMPS = ["Approved", "NotApproved", "Draft", "Final", "Confidential", "ForComment", "ForPublicRelease",
          "NotForPublicRelease", "TopSecret", "Expired", "Sold", "AsIs", "Experimental", "Departmental"]
ZOOMS = ["25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"]
QUALITIES = [("High quality", "high"), ("Medium quality", "medium"), ("Low quality", "low"), ("Minimum quality", "minimum")]

# Tool actions that run one command with values from the action: tool -> (undo label, command, action keys).
# Comment tools also get the author and the tool's colour.
def _ranges(pages0: list[int]) -> str:
    """0-based page list -> '1-3,7' spec."""
    out, i = [], 0
    pages = sorted(set(pages0))
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        out.append(f"{pages[i] + 1}" if i == j else f"{pages[i] + 1}-{pages[j] + 1}")
        i = j + 1
    return ",".join(out)




class Cancelled(Exception):
    """The user pressed Cancel in a progress dialog; the step is undone without an error box."""


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pdfdesk")
        dialogs.size_for_screen(self, 1360, 900)
        self.author = getpass.getuser()
        self.tool = "hand"
        self.stamp_name = "Approved"
        self.sig_spec: dict | None = None
        self.restart_cmd: list[str] | None = None
        self._incoming: dict[str, list[str]] = {}
        self._launches: dict[str, int] = {}
        self._batch_timer = QTimer(self, singleShot=True)
        self._batch_timer.timeout.connect(self._run_batch)
        self.tool_buttons: dict[str, list[QToolButton]] = {}
        self.tool_colors: dict[str, tuple] = {k: tuple(c) for k, c in prefs.get_json("tool_colors", {}).items()}
        self.color_buttons: list[dialogs.ColorButton] = []
        self._handlers = self._build_handlers()

        self.ribbon = Ribbon()
        self.find_box = self.ribbon.find
        self.find_box.returnPressed.connect(self.do_find)
        for name in RIBBON:
            self.ribbon.add_tab(name)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.ribbon)
        v.addWidget(self._build_qat())

        # navigation pane: icon strip + panel, left of the document tabs
        self.thumbs, self.bookmarks, self.comments = Thumbnails(), Bookmarks(), Comments()
        self.attachments = QListWidget()
        self.attachments.itemDoubleClicked.connect(self._save_attachment)
        self.nav_stack = QStackedWidget()
        self.nav = QWidget()
        nl = QHBoxLayout(self.nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        strip = QFrame()
        strip.setObjectName("navStrip")
        strip.setStyleSheet("#navStrip{background:#ececec;border-right:1px solid #d0d0d0}")
        sl = QVBoxLayout(strip)
        sl.setContentsMargins(3, 4, 3, 4)
        sl.setSpacing(2)
        self.nav_buttons = []
        for i, (w, name, ic) in enumerate(((self.thumbs, "Page thumbnails", "pages"),
                                           (self.bookmarks, "Bookmarks", "bookmarks"),
                                           (self.comments, "Comments", "comments"),
                                           (self.attachments, "Attachments", "attachments"))):
            self.nav_stack.addWidget(w)
            b = QToolButton()
            b.setIcon(icon(ic, 24))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(tr(name))
            b.setCheckable(True)
            b.setFixedSize(30, 30)
            b.clicked.connect(lambda _=False, k=i: self._show_nav(k))
            sl.addWidget(b)
            self.nav_buttons.append(b)
        sl.addStretch(1)
        nl.addWidget(strip)
        nl.addWidget(self.nav_stack, 1)
        self.nav.setMinimumWidth(170)

        self.docs = QTabWidget(tabsClosable=True, movable=False, documentMode=True)
        self.docs.tabCloseRequested.connect(self.close_tab)
        self.start = StartPage()
        self.start.openFile.connect(self.open_path)
        self.start.openDialog.connect(self.open_dialog)
        self.start.action.connect(self._start_action)
        self.docs.addTab(self.start, tr("Start"))
        self.docs.tabBar().setTabButton(0, QTabBar.RightSide, None)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.nav)
        self.splitter.addWidget(self.docs)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([230, 1100])
        self.splitter.setChildrenCollapsible(False)
        v.addWidget(self.splitter, 1)
        v.addWidget(self._build_bottom_bar())
        self.setCentralWidget(central)
        self._show_nav(0)
        self.nav.setVisible(False)

        self.thumbs.activated_page.connect(lambda i: self.cur() and self.cur().goto(i))
        self.bookmarks.activated_page.connect(lambda i: self.cur() and self.cur().goto(i))
        self.bookmarks.command.connect(self.bookmark_command)
        self.comments.activated.connect(self._focus_comment)
        self.comments.command.connect(self._comment_command)
        self.docs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.docs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.thumbs.reordered.connect(self._reorder)
        self.thumbs.pageCommand.connect(self._page_command)
        self._build_ribbon()
        self._shortcuts()
        self.set_tool("hand")
        self.ribbon.set_current("Home")
        self.docs.currentChanged.connect(self._tab_changed)
        self._status()
        self._restore_window()

    def _restore_window(self):
        """Last size, position and maximized state. Qt moves a geometry that is off every current screen back
        onto one, so a remembered second monitor that is gone does not hide the window."""
        geo, sizes = prefs.get("window/geometry"), prefs.get_json("window/split", None)
        if isinstance(geo, QByteArray) and not geo.isEmpty():
            self.restoreGeometry(geo)
        if sizes and len(sizes) == 2 and all(isinstance(n, int) and n > 0 for n in sizes):
            self.splitter.setSizes(sizes)

    def _remember_window(self):
        prefs.put("window/geometry", self.saveGeometry())
        if self.nav.isVisible():
            prefs.put_json("window/split", self.splitter.sizes())

    # ---- plumbing ------------------------------------------------------------------------------------
    def cur(self) -> DocView | None:
        w = self.docs.currentWidget()
        return w if isinstance(w, DocView) else None

    def views(self) -> list[DocView]:
        return [w for w in (self.docs.widget(i) for i in range(self.docs.count())) if isinstance(w, DocView)]

    def _build_qat(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("qat")
        bar.setStyleSheet(f"#qat{{background:{theme.BAR}}}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 1, 6, 1)
        h.setSpacing(1)
        for ic, tip, fn in (("open", "Open (Ctrl+O)", self.open_dialog), ("save", "Save (Ctrl+S)", self.save),
                            ("print", "Print (Ctrl+P)", self.print_doc), ("undo", "Undo (Ctrl+Z)", self.undo),
                            ("redo", "Redo (Ctrl+Y)", self.redo)):
            h.addWidget(Ribbon.tiny(ic, tr(tip), fn, size=16))
        h.addSpacing(8)
        for tool in ("hand", "select"):
            b = Ribbon.tiny(tool, tr(TOOL_HINTS[tool]), lambda t=tool: self.set_tool(t), checkable=True, size=16)
            self.tool_buttons.setdefault(tool, []).append(b)
            h.addWidget(b)
        h.addStretch(1)
        return bar

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("bottomBar")
        bar.setStyleSheet(f"#bottomBar{{background:{theme.BAR};border-top:1px solid {theme.LINE}}}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 2, 8, 2)
        self.msg_label = QLabel("")
        self.msg_label.setStyleSheet("color:#555")
        # a long hint must not widen the window's minimum size (a QLabel asks for its whole text)
        self.msg_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h.addWidget(self.msg_label, 1)
        T = Ribbon.tiny
        h.addWidget(T("first", tr("First page"), lambda: self.cur() and self.cur().goto(0)))
        h.addWidget(T("prev", tr("Previous page"), lambda: self.cur() and self.cur().goto(self.cur().current_page() - 1)))
        self.page_spin = QSpinBox(minimum=1, maximum=1)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.editingFinished.connect(lambda: self.cur() and self.cur().goto(self.page_spin.value() - 1))
        h.addWidget(self.page_spin)
        self.page_total = QLabel("/ 0")
        h.addWidget(self.page_total)
        h.addWidget(T("next", tr("Next page"), lambda: self.cur() and self.cur().goto(self.cur().current_page() + 1)))
        h.addWidget(T("last", tr("Last page"), lambda: self.cur() and self.cur().goto(self.cur().doc.page_count - 1)))
        h.addStretch(1)
        h.addWidget(T("fit-width", tr("Fit width"), self.fit_width))
        h.addWidget(T("fit-page", tr("Fit page (Ctrl+0)"), self.fit_page))
        self.zoom_box = QComboBox(editable=True)
        self.zoom_box.addItems(ZOOMS)
        self.zoom_box.setFixedWidth(84)
        self.zoom_box.activated.connect(lambda _: self._zoom_text())
        self.zoom_box.lineEdit().returnPressed.connect(self._zoom_text)
        h.addWidget(self.zoom_box)
        h.addWidget(T("zoom-out", tr("Zoom out"), lambda: self._zoom(0.8)))
        h.addWidget(T("zoom-in", tr("Zoom in"), lambda: self._zoom(1.25)))
        return bar

    def _zoom_text(self):
        v = self.cur()
        try:
            pct = float(self.zoom_box.currentText().strip().rstrip("%"))
        except ValueError:
            return
        if v:
            v.set_zoom(pct / 100)

    def _show_nav(self, k: int):
        self.nav_stack.setCurrentIndex(k)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == k)
        self.nav.setVisible(True)

    def toggle_nav(self):
        self.nav.setVisible(not self.nav.isVisible())

    def _start_action(self, act: str):
        if act == "create":
            return self.create_from_file()
        if act == "merge":
            return self.combine_files()
        self.open_dialog()
        if self.cur():
            if act == "edit":
                self.ribbon.set_current("Edit")
                self.set_tool("edit-text")
            else:
                self.ribbon.set_current("Organize")
                self._show_nav(0)

    def _shortcuts(self):
        for key, fn in (("Ctrl+O", self.open_dialog), ("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as),
                        ("Ctrl+F", self.find_box.setFocus), ("Alt+Q", self.ribbon.tellme.setFocus),
                        ("Ctrl+W", lambda: self.close_tab(self.docs.currentIndex())),
                        ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+P", self.print_doc), ("F4", self.toggle_nav),
                        ("F3", lambda: self.do_find(1)), ("Shift+F3", lambda: self.do_find(-1)),
                        ("Ctrl+G", lambda: self.do_find(1)),
                        ("Ctrl+0", self.fit_page),
                        ("Ctrl+=", lambda: self._zoom(1.25)), ("Ctrl+-", lambda: self._zoom(0.8))):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            self.addAction(a)

    def _zoom(self, k):
        if self.cur():
            self.cur().set_zoom(self.cur().zoom * k)

    def fit_width(self):
        if self.cur():
            self.cur().fit_width()

    def fit_page(self):
        if self.cur():
            self.cur().fit_page()

    def _tab_changed(self, _=None):
        v = self.cur()
        if v:
            v.set_tool(self.tool)
        self.refresh_panels()
        self._status()
        self._title()

    def _title(self):
        v = self.cur()
        name = (self._name(v) if v else "") + (" *" if v and v.modified else "")
        self.setWindowTitle("pdfdesk" + (f" — {name}" if v else ""))
        if v:
            self.docs.setTabText(self.docs.currentIndex(), name)

    @staticmethod
    def _name(v: DocView) -> str:
        """File name of a saved document; for a new one (combined, converted) the name it will be saved under."""
        return os.path.basename(v.path) if v.path else v.new_name or tr("untitled")

    def refresh_panels(self):
        v = self.cur()
        d = v.doc if v else None
        self.thumbs.set_document(d)
        self.bookmarks.set_document(d)
        self.comments.set_document(d)
        self.attachments.clear()
        if d is not None:
            for name in d.embfile_names():
                self.attachments.addItem(name)

    def _save_attachment(self, item):
        v = self.cur()
        if v:
            dst = QFileDialog.getSaveFileName(self, tr("Save attachment"), item.text())[0]
            if dst:
                with open(dst, "wb") as f:
                    f.write(v.doc.embfile_get(item.text()))

    def _status(self):
        v = self.cur()
        self.page_spin.blockSignals(True)
        if v:
            self.page_spin.setMaximum(max(1, v.doc.page_count))
            self.page_spin.setValue(v.current_page() + 1)
            self.page_total.setText(f"/ {v.doc.page_count}")
            self.zoom_box.setEditText(f"{int(round(v.zoom * 100))}%")
            self.thumbs.follow(v.current_page())
        else:
            self.page_spin.setMaximum(1)
            self.page_total.setText("/ 0")
        self.page_spin.blockSignals(False)

    def msg(self, text: str):
        fm = self.msg_label.fontMetrics()
        self.msg_label.setText(fm.elidedText(text, Qt.ElideRight, max(50, self.msg_label.width() - 4)))
        self.msg_label.setToolTip(text if fm.horizontalAdvance(text) > self.msg_label.width() else "")

    def error(self, title: str, e: Exception | str):
        QMessageBox.warning(self, title, str(e))

    # ---- ribbon construction (layout follows Foxit's tabs and groups) -------------------------------
    def _reg(self, label: str, fn):
        self.ribbon.register(label, fn)
        return fn

    def L(self, text, ic, fn, tip=None):
        self._reg(tr(text), fn)
        return Ribbon.large(tr(text), ic, fn, tip=tr(tip) if tip else None)

    def S(self, text, ic, fn, tip=None):
        self._reg(tr(text), fn)
        return Ribbon.small(tr(text), ic, fn, tip=tr(tip) if tip else None)

    def LM(self, text, ic, entries):
        entries = [(tr(t), f) for t, f in entries]
        for t, f in entries:
            self._reg(f"{tr(text)}: {t}", f)
        return Ribbon.large(tr(text), ic, menu=entries)

    def _tool_button(self, make, text, tool, ic):
        self._reg(tr(text), lambda t=tool: self.set_tool(t))
        b = make(tr(text), ic or tool, lambda t=tool: self.set_tool(t), checkable=True, tip=tr(TOOL_HINTS.get(tool, "")))
        self.tool_buttons.setdefault(tool, []).append(b)
        return b

    def TL(self, text, tool, ic=None):
        return self._tool_button(Ribbon.large, text, tool, ic)

    def TS(self, text, tool, ic=None):
        return self._tool_button(Ribbon.small, text, tool, ic)

    def TI(self, tip, tool, ic=None):
        """Icon-only checkable tool button for grids."""
        self._reg(tr(tip), lambda t=tool: self.set_tool(t))
        b = Ribbon.tiny(ic or tool, tr(tip), lambda t=tool: self.set_tool(t), checkable=True)
        self.tool_buttons.setdefault(tool, []).append(b)
        return b

    def tools_group(self, tab):
        """Hand and Select sit at the left of most Foxit tabs."""
        self.ribbon.group(tab, "Tools", [Ribbon.stack_of(self.TS("Hand", "hand"), self.TS("Select", "select"),
                                                        self.TS("Zoom", "zoom"))])

    def _build_ribbon(self):
        r, L, S, LM, TL, TS, TI = self.ribbon, self.L, self.S, self.LM, self.TL, self.TS, self.TI
        G = r.group
        stack, grid = Ribbon.stack_of, Ribbon.grid_of

        # File
        G("File", "File", [L("Open", "open", self.open_dialog), L("Save", "save", self.save),
                           L("Save As", "save", self.save_as), L("Print", "print", self.print_doc),
                           L("Close", "close", lambda: self.close_tab(self.docs.currentIndex()))])
        G("File", "History", [stack(S("Undo", "undo", self.undo), S("Redo", "redo", self.redo))])
        G("File", "Optimize", [LM("Reduce File Size", "optimize", [(t, lambda q=q: self.optimize(q)) for t, q in QUALITIES]),
                               L("Audit Space Usage", "audit", self.audit_space)])
        G("File", "Language", [LM("Language", "language", [(name, lambda c=c: self.set_language(c))
                                                           for c, name in lang.LANGUAGES.items()])])

        # Home
        self.tools_group("Home")
        G("Home", "View", [L("Fit Width", "fit-width", self.fit_width), L("Fit Page", "fit-page", self.fit_page),
                           stack(S("Zoom In", "zoom-in", lambda: self._zoom(1.25)),
                                 S("Zoom Out", "zoom-out", lambda: self._zoom(0.8)))])
        G("Home", "Find", [L("Advanced Search", "search-folder", self.folder_search)])
        G("Home", "Create", [L("From File", "create", self.create_from_file), L("Combine", "combine", self.combine_files)])
        G("Home", "Edit", [TL("Edit Text", "edit-text"), TL("Edit Object", "edit-object"), TL("Add Text", "add-text")])
        G("Home", "Review", [stack(TS("Highlight", "highlight"), TS("Note", "note"), TS("Typewriter", "typewriter")),
                             stack(self._color_button())])
        G("Home", "Protect", [L("Sign", "sign", lambda: self.set_tool("sign-place")),
                              L("Auto Redact", "auto-redact", self.auto_redact),
                              stack(S("Mark Redaction", "redact", lambda: self.set_tool("redact")),
                                    S("Apply", "apply", self.apply_redactions))])

        # Convert
        G("Convert", "Create", [L("From File", "create", self.create_from_file), L("Combine Files", "combine", self.combine_files)])
        G("Convert", "Export", [LM("To Word", "word", [("Word (.docx)", lambda: self.export("docx")),
                                                        ("Rich text (.rtf)", lambda: self.export("rtf"))]),
                                L("To Excel", "excel", lambda: self.export("xlsx")),
                                L("To PowerPoint", "ppt", lambda: self.export("pptx")),
                                LM("To Image", "images", [("PNG", lambda: self.export("png")),
                                                         ("JPEG", lambda: self.export("jpg")),
                                                         ("TIFF", lambda: self.export("tiff"))]),
                                stack(S("To Text", "text", lambda: self.export("txt")),
                                      S("To HTML", "html", lambda: self.export("html")))])
        G("Convert", "OCR", [L("OCR", "ocr", self.ocr)])
        G("Convert", "Standards", [L("To PDF/A", "pdfa", self.to_pdfa)])

        # Edit
        self.tools_group("Edit")
        G("Edit", "Content", [TL("Edit Text", "edit-text"), TL("Edit Object", "edit-object"), TL("Add Text", "add-text"),
                              TL("Add Image", "image")])
        G("Edit", "Find", [L("Replace", "replace", self.find_replace)])
        G("Edit", "Links", [TL("Link", "link"), stack(S("Create from URLs", "link", lambda: self._count(
                                "Create links", lambda d: run("Links.Detect", d), "{n} link(s) created")),
                                S("Remove All Links", "delete", lambda: self._count(
                                    "Remove links", lambda d: run("Links.Remove", d), "{n} link(s) removed")))])
        G("Edit", "Document", [L("Properties", "properties", self.properties)])

        # Fill & Sign
        self.tools_group("Fill & Sign")
        G("Fill & Sign", "Sign", [L("Create Signature", "sign", self.create_signature),
                                  TL("Place Signature", "sign-place", "sign"), self._saved_sig_menu(),
                                  L("Signer Details", "id", lambda: dialogs.SignerDialog.ask(self, self.author))])
        G("Fill & Sign", "Fill", [TL("Add Text", "add-text")])

        # Organize
        self.tools_group("Organize")
        G("Organize", "Pages", [L("Delete", "delete", self.delete_pages), L("Extract", "extract", self.extract_pages),
                                L("Insert Blank", "insert", self.insert_blank), L("Insert File", "insert-file", self.insert_file),
                                stack(S("Rotate Right", "rotate-r", lambda: self._pages_cmd("Rotate", "Pages.Rotate", angle=90)),
                                      S("Rotate Left", "rotate-l", lambda: self._pages_cmd("Rotate", "Pages.Rotate", angle=270)),
                                      S("Reverse", "reverse", lambda: self.apply(tr("Reverse pages"), lambda d: run("Pages.Reverse", d))))])
        G("Organize", "Bookmarks", [L("From Headings", "bookmarks", lambda: self.bookmark_command("from-headings", -1)),
                                    S("Add Bookmark", "bookmarks", lambda: self.bookmark_command("add", -1))])
        G("Organize", "Files", [L("Combine", "combine", self.combine_files), L("Split", "split", self.split)])
        G("Organize", "Page Layout", [stack(S("Crop White", "crop", lambda: self._pages_cmd("Crop", "Pages.Crop", remove_white=True)),
                                            S("Flatten", "flatten", lambda: self.apply(tr("Flatten"), lambda d: run("Pages.Flatten", d))))])
        G("Organize", "Marks", [LM("Header & Footer", "header", [("Add…", self.header_footer),
                                    ("Remove all", lambda: self.apply(tr("Remove header/footer"), lambda d: run("Pages.RemoveHeaderFooter", d)))]),
                                LM("Watermark", "watermark", [("Add…", self.watermark),
                                    ("Remove all", lambda: self.apply(tr("Remove watermark"), lambda d: run("Pages.RemoveWatermark", d)))]),
                                LM("Background", "background", [("Add (cream)", lambda: self.apply(tr("Background"), lambda d: run("Pages.Background", d))),
                                    ("Remove", lambda: self.apply(tr("Remove background"), lambda d: run("Pages.RemoveBackground", d)))]),
                                L("Bates", "bates", self.bates)])

        # Comment — same groups as Foxit: Tools | Text Markup | Pin | Typewriter | Drawing | Stamp | Manage
        self.tools_group("Comment")
        G("Comment", "Text Markup", [grid([TI("Highlight", "highlight"), TI("Underline", "underline"),
                                           TI("Strikeout", "strikeout"), TI("Squiggly", "squiggly"),
                                           TI("Replace Text", "replace-text"), TI("Area Highlight", "area-highlight", "highlight")], 3)])
        G("Comment", "Pin", [TL("Note", "note"), TL("File", "file")])
        G("Comment", "Typewriter", [TL("Typewriter", "typewriter"), stack(TS("Callout", "callout"), TS("Textbox", "textbox"))])
        G("Comment", "Drawing", [grid([TI("Rectangle", "rectangle"), TI("Oval", "oval"), TI("Line", "line"),
                                       TI("Arrow", "arrow"), TI("Polygon", "polygon"), TI("Cloud", "cloud"),
                                       TI("Polyline", "polyline"), TI("Pencil", "pencil")], 4)])
        G("Comment", "Color", [stack(self._color_button())])
        stamp = QComboBox()
        for name in STAMPS:
            stamp.addItem(tr(name), name)
        stamp.setFixedWidth(120)
        stamp.currentIndexChanged.connect(lambda _: setattr(self, "stamp_name", stamp.currentData()))
        G("Comment", "Stamp", [TL("Stamp", "stamp"), stack(stamp)])
        G("Comment", "Manage", [L("Delete All", "delete-all", self.delete_all_comments)])

        # View
        self.tools_group("View")
        G("View", "Zoom", [L("Fit Width", "fit-width", self.fit_width), L("Fit Page", "fit-page", self.fit_page),
                           stack(S("Zoom In", "zoom-in", lambda: self._zoom(1.25)), S("Zoom Out", "zoom-out", lambda: self._zoom(0.8)))])
        G("View", "Layers", [L("Layers", "layers", self.layers)])
        G("View", "Panels", [L("Navigation Panels", "navigation", self.toggle_nav, tip="Show or hide the navigation panels (F4)")])
        G("View", "Compare", [L("Compare", "compare", self.compare)])

        # Protect
        self.tools_group("Protect")
        G("Protect", "Redaction", [TL("Mark for Redaction", "redact"),
                                   L("Auto Redact", "auto-redact", self.auto_redact,
                                     tip="Find e-mail addresses, phone numbers, IBANs, card and tax numbers and dates in the whole "
                                         "document, scanned pages included, and mark them"),
                                   L("Apply Redactions", "apply", self.apply_redactions),
                                   stack(S("Search & Redact", "search-redact", self.search_redact),
                                         Ribbon.small(tr("Find Pattern"), "pattern", menu=[(tr(k), lambda k=k: self.pattern_redact(k))
                                                                                           for k in PATTERNS]),
                                         TS("Whiteout", "whiteout"))])
        G("Protect", "Security", [L("Password", "password", self.password), L("Remove Security", "unlock", self.remove_security),
                                  L("Remove Hidden Info", "hidden", lambda: self.apply(tr("Remove hidden info"), lambda d: run("Protect.RemoveHiddenInfo", d)))])
        G("Protect", "Sign & Certify", [TL("Sign", "digital-sign"), L("Certify", "certify", lambda: self.digital_sign(None, certify=True)),
                                        stack(S("Create ID", "id", self.create_id), S("Validate", "validate", self.validate))])

        # Invoice — e-invoices (ZUGFeRD / Factur-X, XRechnung), not a Foxit tab
        G("Invoice", "Create", [L("Create E-Invoice", "invoice", self.invoice_create,
                                  tip="Fill in a form; get a ZUGFeRD PDF/A-3 with the invoice XML inside, or XRechnung XML"),
                                L("Make ZUGFeRD", "embed-xml", self.invoice_embed,
                                  tip="Turn this PDF into a ZUGFeRD file by attaching an e-invoice XML you already have")])
        G("Invoice", "Open", [L("Open XML Invoice", "xml", self.invoice_open_xml,
                                tip="Show an XRechnung or ZUGFeRD XML file as a readable PDF")])
        G("Invoice", "Check", [L("View Invoice Data", "invoice-view", self.invoice_view),
                               L("Check Invoice", "validate", lambda: self.invoice_view(check=True)),
                               stack(S("Save XML", "export", self.invoice_save_xml))])

        # Form — Foxit's Form tab: Tools | Form Fields | Form Recognition | Form Data | Manage
        self.tools_group("Form")
        G("Form", "Form Fields", [grid([TI("Text Field", "field-text"), TI("Check Box", "field-check"),
                                        TI("Radio Button", "field-radio"), TI("Combo Box", "field-combo"),
                                        TI("List Box", "field-list"), TI("Push Button", "field-button"),
                                        TI("Signature Field", "field-sign")], 4)])
        G("Form", "Form Recognition", [L("Recognize Fields", "recognize", lambda: self._count(
            "Form field recognition", lambda d: len(run("Form.Recognize", d)), "{n} field(s) created"))])
        G("Form", "Form Data", [L("Import", "import", self.form_import),
                                LM("Export", "export", [(f"{x.upper()} (.{x})", lambda x=x: self.form_export(x))
                                                        for x in ("fdf", "xfdf", "json", "csv")]),
                                L("Reset Form", "reset", lambda: self.apply(tr("Reset form"), lambda d: run("Form.Reset", d)))])
        G("Form", "Manage", [L("Calculate", "calc", self.form_calculate),
                             stack(S("Flatten Form", "flatten", lambda: self.apply(tr("Flatten form"), lambda d: run("Form.Flatten", d))),
                                   S("Delete All Fields", "delete-all", self.delete_all_fields))])

        for tab, what in NOT_YET.items():
            r.note(tab, tr(what))
        G("Help", "Help", [L("About", "help", lambda: QMessageBox.about(
            self, "pdfdesk", tr("pdfdesk — a PDF editor for Linux.\nBuilt on PyMuPDF, pikepdf, pyHanko, OCRmyPDF, Qt.")))])

    def _saved_sig_menu(self):
        b = Ribbon.large(tr("Saved Signatures"), "sign-place")
        m = QMenu(b)
        m.aboutToShow.connect(lambda: self._fill_sig_menu(m))
        b.setMenu(m)
        b.setPopupMode(QToolButton.InstantPopup)
        return b

    def _fill_sig_menu(self, m):
        m.clear()
        sigs = dialogs.saved_signatures()
        for s in sigs:
            m.addAction(dialogs.describe_signature(s), lambda s=s: self._use_signature(s))
        if not sigs:
            m.addAction(tr("(none saved yet)")).setEnabled(False)

    def _use_signature(self, s: dict):
        self.sig_spec = s
        self.set_tool("sign-place")
        self.msg(tr("Click or drag on the page to place: {what}", what=dialogs.describe_signature(s)))

    # ---- language -----------------------------------------------------------------------------------------
    def set_language(self, code: str):
        if code == lang.language():
            return
        prefs.put("language", code)
        if any(v.modified for v in self.views()):
            return QMessageBox.information(self, tr("Language"), tr("The new language is used the next time pdfdesk "
                                           "starts. Save your documents, then restart."))
        if QMessageBox.question(self, tr("Language"), tr("Restart pdfdesk now to switch the language?")) == QMessageBox.Yes:
            exe = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "pdfdesk.cli"]
            self.restart_cmd = exe + [v.path for v in self.views() if v.path]
            self.close()

    # ---- comment colors ---------------------------------------------------------------------------------
    def _color_button(self):
        b = dialogs.ColorButton(text=tr("Color"))
        b.setToolTip(tr("Color of new comments made with the current tool (Highlight when no comment tool is on)"))
        b.setFixedHeight(22)
        b.changed.connect(self.set_tool_color)
        self.color_buttons.append(b)
        return b

    def _color_tool(self) -> str:
        return self.tool if self.tool in comment_cmds.DEFAULT_COLORS else "highlight"

    def set_tool_color(self, rgb, tool: str | None = None):
        """New comments (or text) made with this tool get this color, now and in later sessions."""
        t = tool or self._color_tool()
        if not rgb:
            return
        self.tool_colors[t] = tuple(rgb)
        prefs.put_json("tool_colors", self.tool_colors)
        self._show_tool_color()
        if self.cur():
            self.cur().viewport().update()
        what = "New {tool} text uses this color" if t == "add-text" else "New {tool} comments use this color"
        self.msg(tr(what, tool=tr(t.replace("-", " "))))

    def _show_tool_color(self):
        t = self._color_tool()
        rgb = self.tool_colors.get(t) or comment_cmds.DEFAULT_COLORS[t]
        for b in self.color_buttons:
            b.set_color(rgb, emit=False)
            b.setText(tr("{tool} color", tool=tr(t.replace("-", " ").capitalize())))

    def comment_properties(self, page: int, xref: int):
        v = self.cur()
        r = dialogs.CommentPropertiesDialog.ask(self, run("Comment.Style", v.doc, page, xref))
        if r:
            self.apply(tr("Comment properties"), lambda d: run("Comment.SetStyle", d, page, xref, **r))

    def _comment_command(self, name: str, page0: int, xref: int):
        v = self.cur()
        if not v:
            return
        self._focus_comment(page0, xref)
        if name == "properties":
            self.comment_properties(page0 + 1, xref)
        elif name == "delete":
            v.selected = None
            self.apply(tr("Delete comment"), lambda d: run("Comment.Delete", d, page0 + 1, xref))
        elif name == "reply":
            r = dialogs.TextDialog.ask(self, tr("Reply"), tr("Reply:"))
            if r:
                self.apply(tr("Reply"), lambda d: run("Comment.Reply", d, page0 + 1, xref, r, author=self.author))
        elif name.startswith("status:"):
            st = name.split(":", 1)[1]
            self.apply(tr("Status {state}", state=tr(st)), lambda d: run("Comment.SetStatus", d, page0 + 1, xref, st, author=self.author))

    def _tab_menu(self, pos):
        i = self.docs.tabBar().tabAt(pos)
        v = self.docs.widget(i)
        if not isinstance(v, DocView):
            return
        self.docs.setCurrentIndex(i)
        m = QMenu(self)
        m.addAction(tr("Save"), self.save)
        m.addAction(tr("Save As…"), self.save_as)
        if v.path:
            m.addAction(tr("Copy file path"), lambda: QApplication.clipboard().setText(v.path))
            m.addAction(tr("Open containing folder"), lambda: subprocess.Popen(["xdg-open", os.path.dirname(v.path)]))
        m.addSeparator()
        m.addAction(tr("Close"), lambda: self.close_tab(self.docs.indexOf(v)))
        m.addAction(tr("Close other tabs"), lambda: [self.close_tab(self.docs.indexOf(w)) for w in self.views() if w is not v])
        m.exec(self.docs.tabBar().mapToGlobal(pos))

    # ---- tools ----------------------------------------------------------------------------------------
    def set_tool(self, tool: str):
        self.tool = tool
        for name, buttons in self.tool_buttons.items():
            for b in buttons:
                b.setChecked(name == tool)
        self._show_tool_color()
        for w in self.views():
            w.set_tool(tool)
        self.msg(tr(TOOL_HINTS.get(tool, "")))

    # ---- tool actions: one handler per feature -------------------------------------------------------------
    # actions that change nothing in the document, so a read-only document allows them
    VIEW_ACTIONS = {"set-tool", "page-command", "find", "app", "tool-color", "object-export", "copy", "hint"}
    # actions that make one new comment, which is selected afterwards (so Delete, the arrow keys or a right-click
    # act on it at once, as in Foxit)
    COMMENT_ACTIONS = {"highlight", "underline", "strikeout", "squiggly", "highlight-note", "replace-text",
                       "area-highlight", "rectangle", "oval", "line", "arrow", "polygon", "cloud", "polyline", "pencil",
                       "stamp", "note", "file", "typewriter", "insert-text", "textbox", "callout"}
    IMAGES = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"

    def on_tool(self, a: dict):
        """A gesture from the view: a dict with "tool" (the action's name) and its arguments."""
        v = self.cur()
        if not v:
            return
        t = a["tool"]
        if t not in self.VIEW_ACTIONS and v.readonly:
            return self.error(tr("Read only"), tr("This document was opened with its user password and does not "
                                                 "allow changes. Open it with the permissions password to edit."))
        fn = self._handlers.get(t)
        if fn is None:
            return
        page = a.get("page")
        before = self._annot_xrefs(v, page) if t in self.COMMENT_ACTIONS and page else None
        try:
            res = fn(a, page)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Error"), e)
        if before is not None:
            new = self._annot_xrefs(v, page) - before
            if new:
                v.selected, v.obj_sel = (page - 1, max(new)), None
                v.viewport().update()
        return res

    @staticmethod
    def _annot_xrefs(v: DocView, page: int) -> set[int]:
        p = v.doc[page - 1]
        return {a.xref for a in p.annots() or []}

    def _build_handlers(self) -> dict:
        """Action name -> handler(a, page). Grouped by feature; each runs one command as one undoable step."""
        def cmd(label, name, *args, **kw):
            return self.apply(tr(label), lambda d: run(name, d, *args, **kw))

        def cw(a):                              # the color of a new comment: the gesture's, else the tool's
            col = a.get("color") or self.tool_colors.get(a["tool"])
            return {"color": col} if col else {}

        def asked(title, label, then):          # a text dialog, then the command with its text
            r = dialogs.TextDialog.ask(self, tr(title), tr(label))
            return then(r) if r else None

        def typed(a, title, label, then):       # text typed on the page, else asked for
            return then(a["text"]) if a.get("text") else asked(title, label, then)

        def pick_file(title, filt=""):
            return QFileDialog.getOpenFileName(self, tr(title), "", tr(filt) if filt else "")[0]

        app = {
            "set-tool": lambda a, p: self.set_tool(a["name"]),
            "page-command": lambda a, p: self._page_command(a["name"], a["pages"]),
            "find": lambda a, p: (self.find_box.setText(a["text"]), self.do_find()),
            "app": lambda a, p: {"find": lambda: (self.find_box.setFocus(), self.find_box.selectAll()),
                                 "print": self.print_doc, "properties": self.properties}[a["name"]](),
            "tool-color": lambda a, p: self._remember_tool_color(a["name"], a["color"]),
            "hint": lambda a, p: self.msg(a["text"]),
        }
        comments = {
            "delete-annot": lambda a, p: cmd("Delete comment", "Comment.Delete", p, a["xref"]),
            "annot-rect": lambda a, p: cmd("Resize comment", "Comment.SetRect", p, a["xref"], a["rect"]),
            "move-annot": lambda a, p: cmd("Nudge comment" if a.get("nudge") else "Move comment", "Comment.Move", p,
                                           a["xref"], a["dx"], a["dy"]),
            "annot-to-page": lambda a, p: self._select_comment(a["to_page"], cmd(
                tr("Move comment to page {n}", n=a["to_page"]), "Comment.Transfer", p, a["xref"], a["to_page"], a["rect"])),
            "edit-annot": lambda a, p: self.comment_properties(p, a["xref"]),
            "annot-style": lambda a, p: cmd("Comment properties", "Comment.SetStyle", p, a["xref"], **a["style"]),
            "annot-reply": lambda a, p: asked("Reply", "Reply:", lambda r: cmd(
                "Reply", "Comment.Reply", p, a["xref"], r, author=self.author)),
            "annot-status": lambda a, p: cmd(tr("Status {state}", state=tr(a["state"])), "Comment.SetStatus", p, a["xref"], a["state"],
                                             author=self.author),
        }
        objects_ = {
            "object-rect": lambda a, p: cmd("Nudge object" if a.get("nudge") else "Move object", "Object.Transform", p,
                                            a["index"], a["rect"]),
            "delete-object": lambda a, p: cmd("Delete object", "Object.Delete", p, a["index"]),
            "object-turn": lambda a, p: (cmd("Flip object", "Object.Flip", p, a["index"], a["flip"] == "h") if "flip" in a
                                         else cmd("Rotate object", "Object.Rotate", p, a["index"], a["angle"])),
            "object-geometry": lambda a, p: (r := dialogs.GeometryDialog.ask(self, a["rect"])) and cmd(
                "Position and size", "Object.Transform", p, a["index"], r),
            "object-fontsize": lambda a, p: self._reselect_object(p, cmd("Font size", "Object.FontSize", p, a["index"], a["size"])),
            "object-to-page": lambda a, p: self._select_last_object(a["to_page"], cmd(
                tr("Move object to page {n}", n=a["to_page"]), "Object.Transfer", p, a["index"], a["to_page"], a["rect"])),
            "object-export": lambda a, p: self._export_object(p, a["index"]),
        }
        clip = {
            "copy": lambda a, p: self._copy(),
            "cut": lambda a, p: self._cut(),
            "paste": lambda a, p: self._paste(p, a.get("point")),
        }
        markup = {
            **{t: (lambda a, p, n=n: cmd(n, f"Comment.{n}", p, a["start"], a["stop"], author=self.author, **cw(a)))
               for t, n in (("highlight", "Highlight"), ("underline", "Underline"), ("strikeout", "Strikeout"),
                            ("squiggly", "Squiggly"))},
            "highlight-note": lambda a, p: asked("Note on text", "Note:", lambda r: cmd(
                "Highlight with note", "Comment.Highlight", p, a["start"], a["stop"], author=self.author, note=r, **cw(a))),
            "replace-text": lambda a, p: asked("Replace text", "Replacement text:", lambda r: cmd(
                "Replace text", "Comment.ReplaceText", p, a["start"], a["stop"], r, author=self.author)),
            "area-highlight": lambda a, p: a["rect"] and cmd("Area highlight", "Comment.AreaHighlight", p, a["rect"],
                                                             author=self.author, **cw(a)),
        }
        shapes = {
            **{t: (lambda a, p, n=n: a["rect"] and cmd(n, f"Comment.{n}", p, a["rect"], author=self.author, **cw(a)))
               for t, n in (("rectangle", "Rectangle"), ("oval", "Oval"))},
            **{t: (lambda a, p, n=n: cmd(n, f"Comment.{n}", p, a["start"], a["stop"], author=self.author, **cw(a)))
               for t, n in (("line", "Line"), ("arrow", "Arrow"))},
            **{t: (lambda a, p, n=n: cmd(n, f"Comment.{n}", p, a["points"], author=self.author, **cw(a)))
               for t, n in (("polygon", "Polygon"), ("cloud", "Cloud"), ("polyline", "Polyline"))},
            "pencil": lambda a, p: cmd("Pencil", "Comment.Pencil", p, a["strokes"], author=self.author, **cw(a)),
            "stamp": lambda a, p: a["rect"] and cmd("Stamp", "Comment.Stamp", p, a["rect"], self.stamp_name, author=self.author),
        }
        text = {
            "note": lambda a, p: typed(a, "Note", "Note text:", lambda r: cmd(
                "Note", "Comment.Note", p, a["point"], r, author=self.author, **cw(a))),
            "file": lambda a, p: (f := pick_file("Attach file")) and cmd(
                "Attach file", "Comment.File", p, a["point"], f, author=self.author),
            "typewriter": lambda a, p: self._typed_text(a, "Typewriter", lambda r: cmd(
                "Typewriter", "Comment.Typewriter", p, a["point"], r["text"], fontsize=r["size"], color=r["color"],
                author=self.author)),
            "add-text": lambda a, p: self._select_last_object(p, self._typed_text(a, "Add text", lambda r: cmd(
                "Add text", "Text.Add", p, a["point"], r["text"], fontsize=r["size"], color=r["color"]))),
            "insert-text": lambda a, p: asked("Insert text", "Text to insert:", lambda r: cmd(
                "Insert text", "Comment.InsertText", p, a["point"], r, author=self.author)),
            "textbox": lambda a, p: a["rect"] and typed(a, "Text box", "Text:", lambda r: cmd(
                "Text box", "Comment.Textbox", p, a["rect"], r, author=self.author)),
            "callout": lambda a, p: typed(a, "Callout", "Text:", lambda r: cmd(
                "Callout", "Comment.Callout", p, a["start"],
                pymupdf.Rect(a["stop"].x, a["stop"].y, a["stop"].x + 140, a["stop"].y + 50), r, author=self.author)),
            "edit-text-commit": lambda a, p: cmd("Edit text", "Text.EditLine", p, a["point"], a["text"],
                                                 size=a.get("size"), color=a.get("color")),
        }
        page = {
            "bookmark-here": self._bookmark_here,
            "redact-rects": lambda a, p: (cmd("Mark for redaction", "Redact.MarkRects", p, a["rects"]), self.msg(
                tr("Marked for redaction — use Protect > Apply Redactions to remove it permanently"))),
            "redact": lambda a, p: a["rect"] and cmd("Mark for redaction", "Redact.MarkRects", p, [a["rect"]]),
            "whiteout": lambda a, p: a["rect"] and cmd("Whiteout", "Redact.Whiteout", p, [a["rect"]]),
            "image": lambda a, p: a["rect"] and (f := pick_file("Image", self.IMAGES)) and cmd(
                "Add image", "Sign.Image", p, a["rect"], path=f),
            "image-here": lambda a, p: (f := pick_file("Image", self.IMAGES)) and self._place_image(
                p, a["point"], open(f, "rb").read()),
            "sign-place": lambda a, p: self._place_signature(a),
            "digital-sign": lambda a, p: a["rect"] and self.digital_sign(a),
            "link": lambda a, p: a["rect"] and self.add_link(p, a["rect"]),
            "fill-field": lambda a, p: self.fill_field(p, a["xref"]),
            "field-value": lambda a, p: self.apply(tr("Fill field"), lambda d: run("Form.SetField", d, p, a["xref"], a["value"])),
            "field-reset": lambda a, p: cmd("Clear field" if a["names"] else "Reset form", "Form.Reset", a["names"]),
            "field-delete": self._field_delete,
            **{f"field-{k}": (lambda a, p, k=k: a["rect"] and self.add_field(k, p, a["rect"]))
               for k in ("text", "check", "radio", "combo", "list", "button", "sign")},
        }
        return {**app, **comments, **objects_, **clip, **markup, **shapes, **text, **page}

    # ---- helpers of the handlers -------------------------------------------------------------------------------
    def _typed_text(self, a: dict, title: str, then):
        """Text typed on the page (a["text"]), else asked for in a dialog, with the size and color last used by
        this tool; remember them, then run then(r)."""
        tool = a["tool"]
        size = prefs.get_float(f"text_size/{tool}", 10.0)
        color = self.tool_colors.get(tool) or comment_cmds.DEFAULT_COLORS.get(tool, (0, 0, 0))
        if a.get("text"):
            r = {"text": a["text"], "size": a.get("size") or size, "color": a.get("color") or color}
        else:
            r = dialogs.TextDialog.ask(self, tr(title), tr("Text:"), size=size, color=color)
        if not r:
            return None
        prefs.put(f"text_size/{tool}", r["size"])
        if r["color"] and tuple(r["color"]) != tuple(color):
            self._remember_tool_color(tool, r["color"])
        return then(r)

    def _bookmark_here(self, a, page):
        title, ok = QInputDialog.getText(self, tr("Add bookmark"), tr("Title:"), text=a["title"] or tr("Page {n}", n=page))
        return ok and title and self.apply(tr("Add bookmark"), lambda d: run("Bookmarks.Add", d, title, page))

    def _field_delete(self, a, _page):
        if QMessageBox.question(self, tr("Delete field"), tr("Delete the field “{name}”?", name=a["name"])) == QMessageBox.Yes:
            self.apply(tr("Delete field"), lambda d: run("Form.DeleteField", d, a["name"]))

    def _select_comment(self, page: int, xref):
        if xref and self.cur():
            v = self.cur()
            v.selected, v.obj_sel = (page - 1, xref), None
            v.viewport().update()

    def _select_last_object(self, page: int, result):
        if result is not None and self.cur():
            self.cur().select_last_object(page - 1)

    def _reselect_object(self, page: int, result):
        """After an object changed shape, select it again where it is now (its number is unchanged)."""
        v = self.cur()
        if result is not None and v and v.obj_sel:
            v.obj_sel = (page - 1, v.obj_sel[1])
            v.viewport().update()

    # ---- clipboard ------------------------------------------------------------------------------------------
    def _copy(self):
        label = clipboard.copy_selection(self.cur())
        self.msg(tr(label) if label else tr("Nothing selected to copy"))

    def _cut(self):
        v = self.cur()
        if clipboard.copy_selection(v):
            v.delete_selected()

    def _paste(self, page: int, point=None):
        v = self.cur()
        act = clipboard.paste_action(v, page, point)
        if act is None:
            return self.msg(tr("Nothing to paste"))
        label, fn, select = act
        res = self.apply(tr(label), fn)
        if res is not None:
            select(v, res)

    def _place_image(self, page: int, point, data: bytes):
        label, fn = clipboard.image_action(self.cur(), page, point, data)
        return self._select_last_object(page, self.apply(tr(label), fn))

    def _place_signature(self, a):
        if self.sig_spec is None:
            self.sig_spec = dialogs.SignatureDialog.ask(self, self.author)
            if self.sig_spec is None:
                return
        s, page = self.sig_spec, a["page"]
        rect = a["rect"] or pymupdf.Rect(a["point"].x - 80, a["point"].y - 25, a["point"].x + 80, a["point"].y + 25)

        def go(d):
            from ..commands import sign
            return run("Sign.Place", d, page, rect, s, sign.caption_lines(dialogs.signer_profile()))
        placed = self.apply(tr("Signature"), go)
        if placed is not None:          # select it, so it can be moved or resized right away
            self.set_tool("edit-object")
            self.cur().select_object_at(page - 1, placed.tl + (placed.br - placed.tl) / 2)
            self.msg(tr("Signature placed. Drag to move it, drag a corner to resize, Delete removes it."))

    def _export_object(self, page: int, index: int):
        v = self.cur()
        data, ext = run("Object.ExportImage", v.doc, page, index)
        base = os.path.splitext(os.path.basename(v.path or "document"))[0]
        p = QFileDialog.getSaveFileName(self, tr("Export as image"), f"{base}_p{page}_object{index}.{ext}",
                                        f"{tr('Image')} (*.{ext})")[0]
        if p:
            with open(p, "wb") as f:
                f.write(data)
            self.msg(tr("Saved {path}", path=p))

    # ---- applying edits ----------------------------------------------------------------------------
    def apply(self, label: str, fn):
        """Run fn(doc) as one undoable step. A failure restores the document and shows the error."""
        v = self.cur()
        if not v:
            return
        if v.readonly:
            return self.error(tr("Read only"), tr("This document does not allow changes."))
        v.checkpoint(label)
        try:
            res = fn(v.doc)
        except Exception as e:  # noqa: BLE001
            v.rollback()
            v.modified = bool(v.undo_stack) or v.modified
            if isinstance(e, Cancelled):
                self.msg(tr("Cancelled: {what}", what=label))
            else:
                self.error(label, e)
            return None
        if isinstance(res, pymupdf.Document) and res is not v.doc:
            v.replace_doc(res)
        else:
            v.after_edit()
        self._after(v)
        self.msg(label)
        return res

    def _after(self, v):
        self.refresh_panels()
        self._status()
        self._title()

    def undo(self):
        v = self.cur()
        if v and (label := v.undo()):
            self._after(v)
            self.msg(tr("Undid: {what}", what=label))

    def redo(self):
        v = self.cur()
        if v and (label := v.redo()):
            self._after(v)
            self.msg(tr("Redid: {what}", what=label))

    # ---- open / save / close -----------------------------------------------------------------------------
    def open_path(self, path: str) -> DocView | None:
        try:
            doc = pymupdf.open(path)
        except Exception as e:  # noqa: BLE001
            self.error(tr("Open"), e)
            return None
        pw, auth = None, 0
        if doc.needs_pass:
            for _ in range(3):
                pw, ok = QInputDialog.getText(self, tr("Password"), tr("Password for {name}:", name=os.path.basename(path)),
                                              QLineEdit.Password)
                if not ok:
                    return None
                auth = doc.authenticate(pw)
                if auth:
                    break
                QMessageBox.warning(self, tr("Password"), tr("That password is not correct."))
            else:
                return None
        v = DocView(doc, path, pw)
        v.security = sec.from_open(doc, pw, auth)
        v.readonly = sec.restricted(doc, auth)
        if v.readonly:
            QMessageBox.information(self, tr("Restricted"), tr("This file was opened with its user password and does not "
                                    "allow changes. You can read and print it but not edit it."))
        self._add(v, os.path.basename(path))
        self._announce_invoice(v)
        add_recent(path)
        self.start.refresh()
        return v

    def _add(self, v: DocView, title: str):
        v.tool_colors = self.tool_colors
        v.toolAction.connect(self.on_tool)
        v.pageChanged.connect(lambda n: self._status())
        v.changed.connect(self._title)
        self.docs.setCurrentIndex(self.docs.addTab(v, title))     # currentChanged runs _tab_changed
        QTimer.singleShot(0, v.fit_width)      # once the tab has its size; later resizes keep it fitted

    def new_doc(self, doc: pymupdf.Document, name: str):
        v = DocView(doc, None)
        v.modified, v.new_name = True, name
        self._add(v, name)

    def open_dialog(self):
        for p in QFileDialog.getOpenFileNames(self, tr("Open"), "", tr("PDF (*.pdf);;All files (*)"))[0]:
            self.open_path(p)

    def close_tab(self, i):
        v = self.docs.widget(i)
        if not isinstance(v, DocView):
            return
        if v.modified:
            r = QMessageBox.question(self, tr("Close"), tr("Save changes to {name}?", name=self._name(v)),
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                self.docs.setCurrentIndex(i)
                if not self.save():
                    return False
        self.docs.removeTab(i)
        v.deleteLater()
        return True

    def closeEvent(self, e):
        for i in range(self.docs.count() - 1, 0, -1):
            if self.close_tab(i) is False:
                self.restart_cmd = None
                e.ignore()
                return
        self._remember_window()
        e.accept()

    def save(self) -> bool:
        v = self.cur()
        if not v:
            return False
        if not v.path:
            return self.save_as()
        return self._save_to(v, v.path, incremental=True)

    def save_as(self) -> bool:
        v = self.cur()
        if not v:
            return False
        p = QFileDialog.getSaveFileName(self, tr("Save As"), v.path or self._name(v), tr("PDF (*.pdf)"))[0]
        return bool(p) and self._save_to(v, p, incremental=False)

    def _save_to(self, v: DocView, path: str, incremental: bool) -> bool:
        v._commit_editor()          # a text edit still open in the page counts
        s = v.security
        try:
            if s is not None and not s.complete:
                if v.readonly:
                    return self.error(tr("Save"), tr("This document is read only.")) or False
                if s.owner_pw is not None and s.user_pw is None:
                    pw, ok = QInputDialog.getText(self, tr("Open password"), tr("Enter the document's open password to "
                                                  "keep it protected (leave empty for none):"), QLineEdit.Password)
                    if not ok:
                        return False
                    s.user_pw = pw
                elif s.user_pw is not None and s.owner_pw is None:
                    pw, ok = QInputDialog.getText(self, tr("Permissions password"), tr("Enter the permissions password to "
                                                  "keep it protected:"), QLineEdit.Password)
                    if not ok or not pw:
                        return False
                    s.owner_pw = pw
            same = v.doc.name == path
            v.doc = sec.save(v.doc, path, s, incremental and same)
        except Exception as e:  # noqa: BLE001
            self.error(tr("Save"), e)
            return False
        v.path, v.modified = path, False
        if not incremental:
            v.undo_stack.clear()
        add_recent(path)
        self.start.refresh()
        v.relayout()
        self._title()
        self.refresh_panels()
        self.msg(tr("Saved {path}", path=path))
        return True

    def print_doc(self):
        v = self.cur()
        if not v:
            return
        out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True).stdout.split()
        if not out:
            return self.error(tr("Print"), tr("No printers are configured (CUPS)."))
        name, ok = QInputDialog.getItem(self, tr("Print"), tr("Printer:"), out, 0, False)
        if not ok:
            return
        n, ok = QInputDialog.getInt(self, tr("Print"), tr("Copies:"), 1, 1, 99)
        if not ok:
            return
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(v.doc.tobytes())
        r = subprocess.run(["lp", "-d", name, "-n", str(n), f.name], capture_output=True, text=True)
        self.msg(r.stdout.strip() or r.stderr.strip())

    # ---- find / panels --------------------------------------------------------------------------------
    def do_find(self, step: int = 1):
        """Enter in the Find box: search; Enter again (or F3, Shift+F3 back) steps through the hits."""
        v = self.cur()
        text = self.find_box.text()
        if v and text and text == v.find_text and v.hits:
            v.show_hit(v.hit + step)
            return self.msg(tr("Match {i} of {n}", i=v.hit + 1, n=len(v.hits)))
        if v:
            n = v.find(text)
            if n == 0 and not any(v.doc[i].get_text("text").strip() for i in range(min(v.doc.page_count, 5))):
                return self.msg(tr("This document has no text layer (a scan). Run Convert > OCR to search it."))
            self.msg(tr("Match {i} of {n}", i=v.hit + 1, n=n) if n else tr("No matches for “{text}”", text=text))

    def _focus_comment(self, page0: int, xref: int):
        v = self.cur()
        if v:
            v.goto(page0)
            v.selected = (page0, xref)
            v.viewport().update()

    # ---- pages ---------------------------------------------------------------------------------------------
    def _sel_spec(self) -> str:
        v = self.cur()
        sel = self.thumbs.selected_pages()
        return _ranges(sel) if sel else str(v.current_page() + 1)

    def _pages_cmd(self, label: str, name: str, **kw):
        self.apply(tr(label), lambda d: run(name, d, pages=self._sel_spec(), **kw))

    def delete_pages(self):
        v = self.cur()
        spec = self._sel_spec()
        if v and QMessageBox.question(self, tr("Delete pages"), tr("Delete page(s) {pages}?", pages=spec)) == QMessageBox.Yes:
            self.apply(tr("Delete pages"), lambda d: run("Pages.Delete", d, pages=spec))

    def extract_pages(self):
        v = self.cur()
        if not v:
            return
        spec, ok = QInputDialog.getText(self, tr("Extract pages"), tr("Pages (e.g. 1-3,7):"), text=self._sel_spec())
        if not ok or not spec:
            return
        try:
            out = run("Pages.Extract", v.doc, pages=spec)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Extract"), e)
        self.new_doc(out, f"extract-{spec}.pdf")

    def insert_blank(self):
        v = self.cur()
        if v:
            sel = self.thumbs.selected_pages()
            after = (sel[-1] + 1) if sel else v.current_page() + 1
            r = v.doc[min(after, v.doc.page_count) - 1].rect
            self.apply(tr("Insert blank page"), lambda d: run("Pages.InsertBlank", d, after, r.width, r.height))

    def insert_file(self, after: int | None = None):
        v = self.cur()
        p = QFileDialog.getOpenFileName(self, tr("Insert pages from"), "", tr("PDF (*.pdf)"))[0]
        if v and p:
            sel = self.thumbs.selected_pages()
            at = after if after is not None else ((sel[-1] + 1) if sel else v.current_page() + 1)
            self.apply(tr("Insert pages"), lambda d: run("Pages.InsertFile", d, p, at))

    def _reorder(self, order: list[int]):
        self.apply(tr("Reorder pages"), lambda d: d.select(order))

    def _page_command(self, name: str, pages: list[int]):
        v = self.cur()
        if not v or not pages:
            return
        spec = _ranges(pages)
        if name == "rotate-right":
            self.apply(tr("Rotate"), lambda d: run("Pages.Rotate", d, 90, spec))
        elif name == "rotate-left":
            self.apply(tr("Rotate"), lambda d: run("Pages.Rotate", d, 270, spec))
        elif name == "delete":
            if QMessageBox.question(self, tr("Delete pages"), tr("Delete page(s) {pages}?", pages=spec)) == QMessageBox.Yes:
                self.apply(tr("Delete pages"), lambda d: run("Pages.Delete", d, spec))
        elif name == "extract":
            self.new_doc(run("Pages.Extract", v.doc, spec), f"extract-{spec}.pdf")
        elif name == "duplicate":
            def dup(d):
                for k, i in enumerate(pages):
                    d.fullcopy_page(i + k, pages[-1] + 1 + k)
            self.apply(tr("Duplicate pages"), dup)
        elif name == "insert-blank":
            r = v.doc[pages[-1]].rect
            self.apply(tr("Insert blank page"), lambda d: run("Pages.InsertBlank", d, pages[-1] + 1, r.width, r.height))
        elif name == "insert-file":
            self.insert_file(pages[-1] + 1)

    def split(self):
        v = self.cur()
        if not v:
            return
        dlg = dialogs.SplitDialog(self, bool([t for t in v.doc.get_toc() if t[0] == 1]))
        if dlg.exec() != QDialog.Accepted:
            return
        out = QFileDialog.getExistingDirectory(self, tr("Output folder"))
        if not out:
            return
        parts = run("Pages.Split", v.doc, **dlg.values())
        base = os.path.splitext(os.path.basename(v.path or "document"))[0]
        for k, (name, d) in enumerate(parts, 1):
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
            d.save(os.path.join(out, f"{base}_{k:02d}_{safe}.pdf"), garbage=3, deflate=True)
        self.msg(tr("Wrote {n} files to {folder}", n=len(parts), folder=out))

    def combine_files(self, paths: list[str] | None = None):
        """Foxit's Combine Files: a list to order (drag or Up/Down), then one PDF with a bookmark per file."""
        files = dialogs.CombineDialog.ask(self, paths or [])
        if not files:
            return
        self._busy(tr("Combining {n} files…", n=len(files)))
        try:
            self.new_doc(run("Convert.Combine", files), "combined.pdf")
        except Exception as e:  # noqa: BLE001
            self.error(tr("Combine"), e)

    def open_any(self, path: str):
        """Open a PDF, or convert another supported file (Word, image, …) into a new unsaved PDF."""
        from ..commands.convert import SUPPORTED
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            return self.open_path(path)
        if ext not in SUPPORTED:
            return self.msg(tr("{name} is not a file pdfdesk can open", name=os.path.basename(path)))
        self._busy(tr("Converting {name}…", name=os.path.basename(path)))
        try:
            self.new_doc(run("Convert.FromFile", path), os.path.splitext(os.path.basename(path))[0] + ".pdf")
        except Exception as e:  # noqa: BLE001
            self.error(tr("Create PDF"), f"{os.path.basename(path)}: {e}")

    # ---- files handed over by the file manager or a second launch ---------------------------------------
    BATCH_MS = 1200          # Explorer starts one process per selected file; wait for the rest of them

    def receive(self, action: str, paths: list[str]):
        if self.isMinimized():                  # bring it back as it was: showNormal would un-maximize it
            self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        paths = [p for p in paths if os.path.isfile(p)]
        if action == "open":
            for p in paths:
                self.open_any(p)
            return
        pending = self._incoming.setdefault(action, [])
        pending += [p for p in paths if p not in pending]
        self._launches[action] = self._launches.get(action, 0) + 1
        self._batch_timer.start(self.BATCH_MS)

    def _run_batch(self):
        batch, launches, self._incoming, self._launches = self._incoming, self._launches, {}, {}
        for p in batch.get("convert", []):
            self.open_any(p)
        if batch.get("combine"):
            files = batch["combine"]
            if launches.get("combine", 0) > 1:     # one launch per file (Explorer): arrival order is random
                files.sort(key=lambda p: os.path.basename(p).lower())
            self.combine_files(files)

    def header_footer(self, bates=False):
        d = dialogs.HeaderFooterDialog(self, bates)
        if d.exec() == QDialog.Accepted:
            kw = d.values()
            self.apply(tr("Bates numbering") if bates else tr("Header & footer"), lambda doc: run("Pages.HeaderFooter", doc, **kw))

    def bates(self):
        self.header_footer(bates=True)

    def watermark(self):
        d = dialogs.WatermarkDialog(self)
        if d.exec() == QDialog.Accepted:
            kw = d.values()
            self.apply(tr("Watermark"), lambda doc: run("Pages.Watermark", doc, **kw))

    def delete_all_comments(self):
        if self.cur() and QMessageBox.question(self, tr("Delete comments"), tr("Delete all comments?")) == QMessageBox.Yes:
            def go(d):
                for c in run("Comment.List", d):
                    run("Comment.Delete", d, c["page"], c["xref"])
            self.apply(tr("Delete all comments"), go)

    # ---- edit ----------------------------------------------------------------------------------------------
    def find_replace(self):
        v = self.cur()
        if not v:
            return
        f, ok = QInputDialog.getText(self, tr("Replace"), tr("Find:"), text=self.find_box.text())
        if not ok or not f:
            return
        r, ok = QInputDialog.getText(self, tr("Replace"), tr("Replace “{text}” with:", text=f))
        if not ok:
            return
        n = self.apply(tr("Replace text"), lambda d: run("Text.Replace", d, f, r))
        if n is not None:
            self.msg(tr("{n} replacement(s)", n=n))

    def properties(self):
        v = self.cur()
        if not v:
            return
        d = dialogs.PropertiesDialog(self, v.doc, v.path)
        if d.exec() == QDialog.Accepted:
            vals = d.values()
            self.apply(tr("Properties"), lambda doc: doc.set_metadata({**(doc.metadata or {}), **vals}))

    def _count(self, label: str, fn, what: str):
        """Run an undoable step whose result is a count, and report it; `what` is a tr key with {n}."""
        n = self.apply(tr(label), fn)
        if n is not None:
            self.msg(tr(what, n=n))

    # ---- forms ------------------------------------------------------------------------------------------------
    def fill_field(self, page: int, xref: int):
        v = self.cur()
        f = next((f for f in run("Form.List", v.doc) if f["xref"] == xref), None)
        if f is None or f["readonly"]:
            return
        kind = f["type"]
        if kind in ("checkbox", "radio"):
            value = True if kind == "radio" else not f["value"]
        elif kind in ("combo", "list"):
            opts = f["options"] or [""]
            cur = opts.index(f["value"]) if f["value"] in opts else 0
            value, ok = QInputDialog.getItem(self, f["label"], f"{f['label']}:", opts, cur, kind == "combo")
            if not ok:
                return
        elif kind == "text":
            value, ok = QInputDialog.getMultiLineText(self, f["label"], f"{f['label']}:", f["value"] or "")
            if not ok:
                return
        elif kind == "signature":
            return self.digital_sign({"tool": "digital-sign", "page": page, "rect": pymupdf.Rect(f["rect"]),
                                      "field": f["name"]})
        else:
            return
        self.apply(tr("Fill {field}", field=f["label"]), lambda d: run("Form.SetField", d, page, xref, value))

    def add_field(self, kind: str, page: int, rect):
        k = {"text": "text", "check": "checkbox", "radio": "radio", "combo": "combo", "list": "list",
             "button": "button", "sign": "signature"}[kind]
        kw = {}
        if k == "radio":
            groups = sorted({f["name"] for f in run("Form.List", self.cur().doc) if f["type"] == "radio"}) or ["Group1"]
            g, ok = QInputDialog.getItem(self, tr("Radio button"), tr("Group (buttons in one group exclude each other):"),
                                         groups, len(groups) - 1, True)
            if not ok or not g:
                return
            c, ok = QInputDialog.getText(self, tr("Radio button"), tr("This button's value:"), text=tr("Choice"))
            if not ok or not c:
                return
            kw = {"group": g, "name": c}
        else:
            name, ok = QInputDialog.getText(self, tr("New field"), tr("Field name:"))
            if not ok:
                return
            kw["name"] = name or None
            if k in ("combo", "list"):
                o, ok = QInputDialog.getText(self, tr("Options"), tr("Options, separated by commas:"), text=tr("Option 1, Option 2"))
                if not ok:
                    return
                kw["options"] = [x.strip() for x in o.split(",") if x.strip()]
            if k == "text" and rect.height > 40:
                kw["multiline"] = True
        self.apply(tr("Add {kind} field", kind=tr(k)), lambda d: run("Form.AddField", d, page, rect, k, **kw))

    def form_import(self):
        p = QFileDialog.getOpenFileName(self, tr("Import form data"), "", tr("Form data (*.fdf *.xfdf *.json *.csv)"))[0]
        if p:
            self._count("Import form data", lambda d: run("Form.Import", d, p), "{n} field(s) filled")

    def form_export(self, ext: str):
        v = self.cur()
        if not v:
            return
        base = os.path.splitext(v.path or "form.pdf")[0] + f".{ext}"
        p = QFileDialog.getSaveFileName(self, tr("Export form data"), base, f"{ext.upper()} (*.{ext})")[0]
        if p:
            try:
                n = len(run("Form.Export", v.doc, p, source=os.path.basename(v.path or "form.pdf")))
                self.msg(tr("{n} field(s) exported to {path}", n=n, path=p))
            except Exception as e:  # noqa: BLE001
                self.error(tr("Export form data"), e)

    def form_calculate(self):
        v = self.cur()
        if not v:
            return
        names = sorted({f["name"] for f in run("Form.List", v.doc) if f["type"] == "text"})
        if len(names) < 2:
            return self.error(tr("Calculate"), tr("The form needs at least two text fields."))
        target, ok = QInputDialog.getItem(self, tr("Calculate"), tr("Result field:"), names, 0, False)
        if not ok:
            return
        src, ok = QInputDialog.getText(self, tr("Calculate"), tr("Fields to combine, separated by commas:"),
                                       text=", ".join(n for n in names if n != target))
        if not ok:
            return
        ops = ["sum", "product", "average", "min", "max"]
        op, ok = QInputDialog.getItem(self, tr("Calculate"), tr("Operation:"), [tr(o) for o in ops], 0, False)
        if ok:
            op = ops[[tr(o) for o in ops].index(op)]
            r = self.apply(tr("Calculate"), lambda d: run("Form.Calculate", d, target,
                                                         [x.strip() for x in src.split(",") if x.strip()], op))
            if r is not None:
                self.msg(f"{target} = {r:g}")

    def delete_all_fields(self):
        v = self.cur()
        if v and QMessageBox.question(self, tr("Delete fields"), tr("Delete every form field?")) == QMessageBox.Yes:
            self.apply(tr("Delete all fields"), lambda d: run("Form.DeleteField", d, [f["name"] for f in run("Form.List", d)]))

    # ---- links, bookmarks, layers ------------------------------------------------------------------------------
    def add_link(self, page: int, rect):
        v = self.cur()
        kinds = [tr("Web address"), tr("Page in this document"), tr("Another file")]
        kind, ok = QInputDialog.getItem(self, tr("Create link"), tr("Link to:"), kinds, 0, False)
        if not ok:
            return
        if kind == kinds[0]:
            url, ok = QInputDialog.getText(self, tr("Create link"), "URL:", text="https://")
            if ok and url:
                self.apply(tr("Add link"), lambda d: run("Links.AddUrl", d, page, rect, url))
        elif kind == kinds[1]:
            n, ok = QInputDialog.getInt(self, tr("Create link"), tr("Go to page:"), v.current_page() + 1, 1, v.doc.page_count)
            if ok:
                self.apply(tr("Add link"), lambda d: run("Links.AddPage", d, page, rect, n))
        else:
            p = QFileDialog.getOpenFileName(self, tr("Link to file"))[0]
            if p:
                self.apply(tr("Add link"), lambda d: run("Links.AddFile", d, page, rect, p))

    def bookmark_command(self, what: str, k: int):
        v = self.cur()
        if not v:
            return
        here = v.current_page() + 1
        toc = v.doc.get_toc()
        if what == "from-headings":
            if toc and QMessageBox.question(self, tr("Bookmarks"), tr("Replace the existing bookmarks?")) != QMessageBox.Yes:
                return
            return self._count("Bookmarks from headings", lambda d: run("Bookmarks.FromHeadings", d), "{n} bookmark(s) created")
        if what in ("add", "add-child"):
            t, ok = QInputDialog.getText(self, tr("Add bookmark"), tr("Title:"), text=tr("Page {n}", n=here))
            if not ok or not t:
                return
            if k < 0:
                return self.apply(tr("Add bookmark"), lambda d: run("Bookmarks.Add", d, t, here))
            lvl = toc[k][0] + (1 if what == "add-child" else 0)
            end = k + 1
            while end < len(toc) and toc[end][0] > toc[k][0]:
                end += 1
            return self.apply(tr("Add bookmark"), lambda d: run("Bookmarks.Add", d, t, here, level=lvl,
                                                                index=k + 1 if what == "add-child" else end))
        if what == "rename":
            t, ok = QInputDialog.getText(self, tr("Rename bookmark"), tr("Title:"), text=toc[k][1])
            return ok and t and self.apply(tr("Rename bookmark"), lambda d: run("Bookmarks.Rename", d, k, t))
        if what == "set-page":
            return self.apply(tr("Bookmark destination"), lambda d: run("Bookmarks.SetPage", d, k, here))
        if what in ("promote", "demote"):
            return self.apply(tr(what.capitalize()), lambda d: run("Bookmarks.Indent", d, k, -1 if what == "promote" else 1))
        if what == "delete":
            return self.apply(tr("Delete bookmark"), lambda d: run("Bookmarks.Delete", d, k))

    def layers(self):
        v = self.cur()
        if not v:
            return
        d = dialogs.LayersDialog(self, run("Layers.List", v.doc))
        if d.exec() == QDialog.Accepted:
            vals = d.values()

            def go(doc):
                for x, on in vals.items():
                    run("Layers.SetVisible", doc, x, on)
            self.apply(tr("Layers"), go)

    # ---- optimize and search ------------------------------------------------------------------------------------
    def optimize(self, quality: str):
        v = self.cur()
        if not v:
            return
        before = len(v.doc.tobytes(garbage=4, deflate=True))
        if self.apply(tr("Reduce file size"), lambda d: run("Optimize.Reduce", d, quality)) is None and not v.undo_stack:
            return
        after = len(v.doc.tobytes(garbage=4, deflate=True))
        self.msg(tr("Estimated size {before:.2f} MB → {after:.2f} MB. Save to write it.", before=before / 1e6, after=after / 1e6))

    def audit_space(self):
        v = self.cur()
        if v:
            a = run("Optimize.Audit", v.doc)
            total = sum(a.values()) or 1
            QMessageBox.information(self, tr("Audit Space Usage"), "\n".join(
                f"{tr(k)}: {n / 1024:,.0f} KB ({n * 100 / total:.0f}%)" for k, n in a.items()))

    def folder_search(self):
        def open_hit(path, page):
            w = next((w for w in self.views() if w.path == path), None)
            if w:
                self.docs.setCurrentIndex(self.docs.indexOf(w))
            else:
                w = self.open_path(path)
            if w:
                w.goto(page - 1)
                w.find(dlg.text.text())
        dlg = dialogs.FolderSearchDialog(self, open_hit)
        dlg.show()
        self._search_dlg = dlg

    # ---- protect ----------------------------------------------------------------------------------------------
    def _marked(self, n: int):
        self.msg(tr("{n} item(s) marked — use Apply to remove them permanently", n=n))

    def search_redact(self):
        t, ok = QInputDialog.getText(self, tr("Search & Redact"), tr("Text to mark for redaction:"))
        if ok and t:
            n = self.apply(tr("Search & redact"), lambda d: run("Redact.Search", d, needle=t, ocr_scans=True))
            if n is not None:
                self._marked(n)

    def pattern_redact(self, kind: str):
        n = self.apply(tr("Redact {what}", what=tr(kind)), lambda d: run("Redact.Search", d, kind=kind))
        if n is not None:
            self._marked(n)

    def auto_redact(self):
        """Find personal data everywhere in the document, scans included, review it, mark it (and apply)."""
        v = self.cur()
        if not v:
            return
        has_scans = any(not p.get_text().strip() and p.get_images() for p in v.doc)
        d = dialogs.AutoRedactDialog(self, list(PATTERNS), lambda kinds, ocr_scans, langs, progress: run(
            "Redact.Find", v.doc, kinds=kinds, ocr_scans=ocr_scans, languages=langs, progress=progress), has_scans)
        if d.exec() != QDialog.Accepted or not d.items:
            return
        n = self.apply(tr("Auto redact"), lambda doc: run("Redact.Mark", doc, d.items))
        if n is None:
            return
        if d.apply_now:
            self.apply(tr("Apply redactions"), lambda doc: run("Redact.Apply", doc))
            self.msg(tr("{n} item(s) redacted. Save to write the result.", n=n))
        else:
            self._marked(n)

    def apply_redactions(self):
        v = self.cur()
        if not v:
            return
        n = sum(1 for p in v.doc for _ in p.annots(types=[pymupdf.PDF_ANNOT_REDACT]))
        if not n:
            return self.msg(tr("Nothing is marked for redaction"))
        if QMessageBox.warning(self, tr("Apply redactions"), tr("Permanently remove {n} marked item(s)? This cannot be "
                               "undone after saving.", n=n), QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok:
            self.apply(tr("Apply redactions"), lambda d: run("Redact.Apply", d))

    def password(self):
        v = self.cur()
        if not v:
            return
        s = dialogs.PasswordDialog.ask(self)
        if s:
            v.security = s
            v.readonly = False
            v.modified = True
            self._title()
            self.msg(tr("Password protection will be applied when you save"))

    def remove_security(self):
        v = self.cur()
        if v and v.security:
            if v.readonly:
                return self.error(tr("Security"), tr("Open the document with its permissions password first."))
            v.security = None
            v.modified = True
            self._title()
            self.msg(tr("Security will be removed when you save"))

    def create_id(self):
        p = dialogs.CreateIDDialog.ask(self, self.author)
        if p:
            self.msg(tr("Digital ID saved: {path}", path=p))

    def create_signature(self):
        s = dialogs.SignatureDialog.ask(self, self.author)
        if s:
            self._use_signature(s)

    def digital_sign(self, a: dict | None, certify: bool = False):
        v = self.cur()
        if not v:
            return
        if v.security:
            return self.error(tr("Sign"), tr("Remove password protection before signing; sign, then protect a copy."))
        vals = dialogs.DigitalSignDialog.ask(self, certify, self.author)
        if not vals:
            return
        page = a["page"] if a else None
        field = a.get("field") if a else None
        rect = a["rect"] if a and not vals["invisible"] and not field else None
        if rect is None and not vals["invisible"] and not certify and a is None:
            vals["invisible"] = True
        base = os.path.splitext(v.path or "document.pdf")[0] + ("_certified.pdf" if vals["certify"] else "_signed.pdf")
        dst = QFileDialog.getSaveFileName(self, tr("Save signed copy"), base, tr("PDF (*.pdf)"))[0]
        if not dst:
            return
        try:
            run("Sign.Digital", v.doc.tobytes(), dst, vals["pfx"], vals["password"], page=page, rect=rect,
                reason=vals["reason"], location=vals["location"], certify=vals["certify"], field_name=field)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Sign"), e)
        self.open_path(dst)
        self.msg(tr("Signed. Further edits to a signed file invalidate the signature unless saved incrementally."))

    def validate(self):
        v = self.cur()
        if not v or not v.path:
            return self.error(tr("Validate"), tr("Save the document first."))
        certs = sorted(glob.glob(str(dialogs.IDS / "*.cer")))
        try:
            res = run("Sign.Validate", v.path, trusted_certs=certs)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Validate"), e)
        if not res:
            return QMessageBox.information(self, tr("Signatures"), tr("This document has no digital signatures."))
        lines = []
        for r in res:
            state = tr("VALID") if r["valid"] and r["intact"] else tr("INVALID")
            trusted = tr("yes (your own ID)") if r["trusted"] else tr("no")
            lines.append(f"{r['field']}: {state}\n  {tr('Signer')}: {r['signer']}\n  {tr('Trusted')}: {trusted}\n"
                         f"  {tr('Covers')}: {r['coverage']}   {tr('Changes after signing')}: {r['modification_level']}")
        QMessageBox.information(self, tr("Signatures"), "\n\n".join(lines))

    # ---- compare ----------------------------------------------------------------------------------------------
    def compare(self):
        v = self.cur()
        if not v:
            return
        p = QFileDialog.getOpenFileName(self, tr("Compare current document (old) with… (new)"), "", tr("PDF (*.pdf)"))[0]
        if not p:
            return
        try:
            res, changes = run("Compare.Run", v.doc, pymupdf.open(p))
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Compare"), e)
        self.new_doc(res, "comparison.pdf")
        self.msg(tr("{n} change(s) found", n=len(changes)))

    # ---- convert ----------------------------------------------------------------------------------------------
    def _current_file(self) -> str | None:
        """A path with the current state of the document (a temp copy when it has unsaved changes)."""
        v = self.cur()
        if not v:
            return None
        if v.path and not v.modified:
            return v.path
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(v.doc.tobytes())
        f.close()
        return f.name

    def _progress(self, what: str):
        """A progress dialog for a long job over pages and its callback progress(n, total); Cancel stops the job
        at the next page and undoes it."""
        dlg = QProgressDialog(what, tr("Cancel"), 0, 0, self)
        dlg.setWindowTitle(what)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.setAutoClose(False)

        def progress(n: int, total: int):
            dlg.setMaximum(total)
            dlg.setValue(n)
            dlg.setLabelText(tr("{what}: page {n} of {total}", what=what, n=n + 1, total=total))
            QApplication.processEvents()
            if dlg.wasCanceled():
                raise Cancelled()
        return dlg, progress

    def _busy(self, text: str):
        """Say what a long job is doing and show a wait cursor until the window is idle again, which is when
        the job (run right after this call, in the same event) has finished."""
        self.msg(text)
        if QApplication.overrideCursor() is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QTimer.singleShot(0, QApplication.restoreOverrideCursor)
        QApplication.processEvents()

    def create_from_file(self):
        p = QFileDialog.getOpenFileName(self, tr("Create PDF from file"))[0]
        if p:
            self._busy(tr("Converting…"))
            try:
                self.new_doc(run("Convert.FromFile", p), os.path.splitext(os.path.basename(p))[0] + ".pdf")
            except Exception as e:  # noqa: BLE001
                self.error(tr("Create PDF"), e)

    def export(self, fmt: str):
        v = self.cur()
        if not v:
            return
        base = os.path.splitext(os.path.basename(v.path or "document"))[0]
        try:
            if fmt in ("png", "jpg", "tiff"):
                out = QFileDialog.getExistingDirectory(self, tr("Folder for images"))
                if not out:
                    return
                n = len(run("Convert.ToImages", v.doc, out, fmt=fmt))
                return self.msg(tr("Wrote {n} image(s) to {folder}", n=n, folder=out))
            out = QFileDialog.getSaveFileName(self, tr("Export"), f"{base}.{fmt}")[0]
            if not out:
                return
            self._busy(tr("Exporting…"))
            by_path = {"docx": "Convert.ToWord", "rtf": "Convert.ToRtf"}
            by_doc = {"xlsx": "Convert.ToExcel", "pptx": "Convert.ToPowerPoint", "txt": "Convert.ToText", "html": "Convert.ToHtml"}
            if fmt in by_path:
                run(by_path[fmt], self._current_file(), out)
            else:
                run(by_doc[fmt], v.doc, out)
            self.msg(tr("Exported {path}", path=out))
        except Exception as e:  # noqa: BLE001
            self.error(tr("Export"), e)

    def ocr(self):
        v = self.cur()
        if not v:
            return
        langs, ok = QInputDialog.getText(self, tr("OCR"), tr("Language (en, de, ar, fr, …; several with +):"),
                                         text=lang.ocr_languages())
        if not ok or not langs.strip():
            return
        kinds = [tr("Editable text — replace the scan with real text you can edit"),
                 tr("Searchable text — keep the image, add an invisible text layer")]
        kind, ok = QInputDialog.getItem(self, tr("OCR"), tr("Output:"), kinds, 0, False)
        if not ok:
            return
        self._busy(tr("Running OCR…"))
        language_list = [x for x in langs.replace(",", "+").split("+") if x.strip()]
        dlg, progress = self._progress(tr("OCR"))
        try:
            self._ocr_run(kind == kinds[0], language_list, progress)
        finally:
            dlg.close()

    def _ocr_run(self, editable: bool, language_list, progress):
        if editable:
            res = self.apply(tr("OCR (editable text)"), lambda d: run("Ocr.Editable", d, languages=language_list,
                                                                     progress=progress))
            if isinstance(res, dict):
                self.msg(tr("OCR done: {pages} page(s), {lines} lines, {suspects} uncertain word(s) to check",
                            pages=res["pages"], lines=res["lines"], suspects=len(res["suspects"])))
            return
        res = self.apply(tr("OCR"), lambda d: run("Ocr.Searchable", d, languages=language_list, progress=progress))
        if isinstance(res, dict):
            self.msg(tr("OCR done: {pages} page(s), {lines} lines", pages=res["pages"], lines=res["lines"]))

    def to_pdfa(self):
        v = self.cur()
        if not v:
            return
        out = QFileDialog.getSaveFileName(self, tr("Save PDF/A copy"), (os.path.splitext(v.path or "document")[0]) + "_pdfa.pdf",
                                          tr("PDF (*.pdf)"))[0]
        if out:
            self._busy(tr("Converting to PDF/A…"))
            try:
                run("Convert.ToPDFA", self._current_file(), out)
                self.open_path(out)
            except Exception as e:  # noqa: BLE001
                self.error(tr("PDF/A"), e)

    # ---- e-invoices ----------------------------------------------------------------------------------------
    def _announce_invoice(self, v: DocView):
        try:
            found = invoice_cmds.find_xml(v.doc)
            std = invoice_cmds.parse(found[1])["standard"] if found else None
        except Exception:  # noqa: BLE001
            return
        if std:
            self.msg(tr("This PDF is an e-invoice ({standard}). Invoice tab > View Invoice Data shows and checks it.", standard=std))

    def invoice_create(self):
        from . import invoice as ui
        r = ui.InvoiceDialog.ask(self)
        if not r:
            return
        inv, out = r["invoice"], r["output"]
        base = "".join(c if c.isalnum() or c in "-_" else "_" for c in inv["number"]) or "invoice"
        folder = prefs.get("invoice/folder", os.path.expanduser("~"))
        pdf = xml = None
        if out in ("pdf", "both"):
            pdf = QFileDialog.getSaveFileName(self, tr("Save e-invoice"), os.path.join(folder, base + ".pdf"), tr("PDF (*.pdf)"))[0]
            if not pdf:
                return
            if out == "both":
                xml = os.path.splitext(pdf)[0] + ".xml"
        else:
            xml = QFileDialog.getSaveFileName(self, tr("Save XRechnung XML"), os.path.join(folder, base + ".xml"), "XML (*.xml)")[0]
            if not xml:
                return
        prefs.put("invoice/folder", os.path.dirname(pdf or xml))
        self._busy(tr("Creating e-invoice (PDF/A-3)…"))
        try:
            res = run("Invoice.Create", inv, out_pdf=pdf, out_xml=xml, lang=r["lang"], design=r["design"],
                      accent=r["accent"], logo=r["logo"])
            errors = [c for c in run("Invoice.Check", pdf or res["xml"]) if c[0] == "error"]
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Create E-Invoice"), e)
        if pdf:
            self.open_path(pdf)
        else:
            self.new_doc(run("Invoice.Visualize", xml, lang=r["lang"]), os.path.basename(xml) + ".pdf")
        what = " + ".join(os.path.basename(x) for x in (pdf, xml) if x)
        self.msg(tr("Saved {what}", what=what) + " — " + (tr("{n} check error(s), see Check Invoice", n=len(errors)) if errors
                                                          else tr("checks passed")))

    def invoice_open_xml(self):
        p = QFileDialog.getOpenFileName(self, tr("Open XML e-invoice"), "", tr("E-invoice XML (*.xml);;All files (*)"))[0]
        if not p:
            return
        try:
            doc = run("Invoice.Visualize", p)
            inv = run("Invoice.Read", p)
            n = sum(1 for c in run("Invoice.Check", inv) if c[0] == "error")
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Open XML invoice"), e)
        self.new_doc(doc, os.path.splitext(os.path.basename(p))[0] + ".pdf")
        self.msg(f"{inv['standard']} {inv['number']} — " + (tr("{n} check error(s)", n=n) if n else tr("checks passed"))
                 + ". " + tr("The XML is attached; save to keep the PDF."))

    def _invoice_of_current(self):
        v = self.cur()
        if not v:
            return None, None
        found = invoice_cmds.find_xml(v.doc)
        if not found:
            self.error(tr("E-invoice"), tr("This PDF has no embedded e-invoice XML (ZUGFeRD / Factur-X / XRechnung)."))
            return None, None
        inv = invoice_cmds.parse(found[1])
        inv["source"] = found[0]
        return inv, found[1]

    def invoice_view(self, check: bool = False):
        from . import invoice as ui
        try:
            inv, xml = self._invoice_of_current()
            if not inv:
                return
            checks = run("Invoice.Check", self.cur().doc)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("E-invoice"), e)
        d = ui.InvoiceViewDialog(self, inv, checks, xml)
        if check:
            d.tabs.setCurrentIndex(1)
        d.exec()

    def invoice_save_xml(self):
        inv, xml = self._invoice_of_current()
        if inv:
            p = QFileDialog.getSaveFileName(self, tr("Save XML"), inv.get("source") or "invoice.xml", "XML (*.xml)")[0]
            if p:
                with open(p, "wb") as f:
                    f.write(xml)
                self.msg(tr("Saved {path}", path=p))

    def invoice_embed(self):
        v = self.cur()
        if not v:
            return
        x = QFileDialog.getOpenFileName(self, tr("E-invoice XML to attach"), "", "XML (*.xml)")[0]
        if not x:
            return
        with open(x, "rb") as f:
            data = f.read()
        try:
            inv = run("Invoice.Read", data)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Make ZUGFeRD"), tr("{name} is not an e-invoice: {error}", name=os.path.basename(x), error=e))
        if inv["syntax"] != "CII":
            return self.error(tr("Make ZUGFeRD"), tr("ZUGFeRD needs CII XML; this is UBL (XRechnung UBL is sent as XML on its own)."))
        out = QFileDialog.getSaveFileName(self, tr("Save ZUGFeRD PDF"), os.path.splitext(v.path or "invoice")[0] + "_zugferd.pdf",
                                          tr("PDF (*.pdf)"))[0]
        if not out:
            return
        self._busy(tr("Converting to PDF/A-3 and attaching the XML…"))
        try:
            run("Invoice.Embed", self._current_file(), data, out)
        except Exception as e:  # noqa: BLE001
            return self.error(tr("Make ZUGFeRD"), e)
        self.open_path(out)


def launch(action: str = "open", files: list[str] = (), lock=None):
    """Start the window. Launches that arrive while it starts are queued and handed over once it exists."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("pdfdesk")
    app.setDesktopFileName("pdfdesk")
    app.setWindowIcon(app_icon())
    code = prefs.get("language") or QLocale.system().name()[:2]
    lang.install(app, code if code in lang.LANGUAGES else "en")
    from .. import instance
    early: list[tuple[str, list[str]]] = []
    window: list[Main] = []
    server = instance.serve(lambda a, p: window[0].receive(a, p) if window else early.append((a, p)))
    w = Main()
    window.append(w)
    w.show()
    for a, p in [(action, list(files))] + early:
        w.receive(a, p)
    rc = app.exec()
    if w.restart_cmd:                       # language change: start afresh with the same files
        if server:
            server.close()
        if lock is not None:
            lock.unlock()
        subprocess.Popen(w.restart_cmd)
    return rc
