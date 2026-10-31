"""Main window laid out like Foxit PhantomPDF: ribbon (File tab, tabs, Tell me, Find), quick access toolbar,
Start page and document tabs, navigation pane with an icon strip, bottom bar with page navigation and zoom."""
from __future__ import annotations

import getpass
import glob
import json
import os
import subprocess
import sys
import tempfile

import pymupdf
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QMainWindow, QMessageBox, QSpinBox, QSplitter, QStackedWidget,
                               QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..commands import comment as comment_cmds
from ..commands import run
from ..core import security as sec
from . import dialogs
from .icons import app_icon, icon
from .panels import Bookmarks, Comments, Thumbnails
from .ribbon import Ribbon
from .start import StartPage, add_recent
from .viewer import DocView

RIBBON = ["File", "Home", "Convert", "Edit", "Fill && Sign", "Organize", "Comment", "View", "Form",
          "Protect", "Share", "Connect", "Accessibility", "Help"]
NOT_YET = {"Share": "Email, shared review and cloud drives",
           "Connect": "Connected services", "Accessibility": "Accessibility check and tagging"}

TOOL_HINTS = {
    "hand": "Hand: drag to scroll; click a comment to select it, drag to move, drag a corner to resize "
            "(Delete removes it, double-click or right-click to change its color, size and text)",
    "select": "Select: drag over text; right-click to highlight, Ctrl+C copies", "zoom": "Zoom: click to zoom in, Shift+click out",
    "highlight": "Highlight: drag across text", "underline": "Underline: drag across text",
    "strikeout": "Strikeout: drag across text", "squiggly": "Squiggly: drag across text",
    "replace-text": "Replace text: drag across the text to replace", "area-highlight": "Area highlight: drag",
    "note": "Note: click where the note goes", "file": "File attachment: click where it goes",
    "typewriter": "Typewriter: click where the text goes", "textbox": "Text box: drag a box",
    "callout": "Callout: drag from the point to the box position",
    "rectangle": "Rectangle: drag", "oval": "Oval: drag", "line": "Line: drag", "arrow": "Arrow: drag",
    "polygon": "Polygon: click points, double-click or Enter to finish",
    "cloud": "Cloud: click points, double-click or Enter to finish",
    "polyline": "Polyline: click points, double-click or Enter to finish",
    "pencil": "Pencil: draw, press Enter to finish", "stamp": "Stamp: drag a box",
    "edit-text": "Edit text: click a line of text and change it; click elsewhere or press Enter to keep it",
    "edit-object": "Edit object: click text, a shape, an image or a signature; drag to move, drag a corner to resize, Delete removes it",
    "add-text": "Add text: click where the text goes", "image": "Add image: drag a box",
    "redact": "Mark for redaction: drag over text or images", "whiteout": "Whiteout: drag over what to erase",
    "sign-place": "Place signature: click or drag a box", "digital-sign": "Digital signature: drag a box",
}
STAMPS = ["Approved", "NotApproved", "Draft", "Final", "Confidential", "ForComment", "ForPublicRelease",
          "NotForPublicRelease", "TopSecret", "Expired", "Sold", "AsIs", "Experimental", "Departmental"]
ZOOMS = ["25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"]


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


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pdfdesk")
        self.resize(1360, 900)
        self.author = getpass.getuser()
        self.tool = "hand"
        self.stamp_name = "Approved"
        self.sig_spec: dict | None = None
        self.tool_buttons: dict[str, list[QToolButton]] = {}
        self.tool_colors: dict[str, tuple] = {k: tuple(c) for k, c in
                                              json.loads(QSettings("pdfdesk", "pdfdesk").value("tool_colors", "{}")).items()}
        self.color_buttons: list[dialogs.ColorButton] = []

        self.ribbon = Ribbon()
        self.find_box = self.ribbon.find
        self.find_box.returnPressed.connect(self.do_find)
        for name in RIBBON:
            self.ribbon.add_tab(name)
        self.groups = self.ribbon.pages

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.ribbon)
        self.qat = self._build_qat()
        v.addWidget(self.qat)

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
            b.setToolTip(name)
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
        self.docs.addTab(self.start, "Start")
        self.docs.tabBar().setTabButton(0, QTabBar.RightSide, None)

        self.split = QSplitter()
        self.split.addWidget(self.nav)
        self.split.addWidget(self.docs)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([230, 1100])
        self.split.setChildrenCollapsible(False)
        v.addWidget(self.split, 1)
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

    # ---- plumbing ------------------------------------------------------------------------------------
    def cur(self) -> DocView | None:
        w = self.docs.currentWidget()
        return w if isinstance(w, DocView) else None

    def _build_qat(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("qat")
        bar.setStyleSheet("#qat{background:#f3f3f3}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 1, 6, 1)
        h.setSpacing(1)
        T = lambda ic, tip, fn, checkable=False: Ribbon.tiny(ic, tip, fn, checkable, size=16)  # Foxit's QAT size
        for ic, tip, fn in (("open", "Open (Ctrl+O)", self.open_dialog), ("save", "Save (Ctrl+S)", self.save),
                            ("print", "Print (Ctrl+P)", self.print_doc), ("undo", "Undo (Ctrl+Z)", self.undo),
                            ("redo", "Redo (Ctrl+Y)", self.redo)):
            h.addWidget(T(ic, tip, fn))
        h.addSpacing(8)
        for tool, ic in (("hand", "hand"), ("select", "select")):
            b = T(ic, TOOL_HINTS[tool], lambda t=tool: self.set_tool(t), checkable=True)
            self.tool_buttons.setdefault(tool, []).append(b)
            h.addWidget(b)
        h.addStretch(1)
        return bar

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("bottomBar")
        bar.setStyleSheet("#bottomBar{background:#f3f3f3;border-top:1px solid #d5d5d5}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 2, 8, 2)
        self.msg_label = QLabel("")
        self.msg_label.setStyleSheet("color:#555")
        h.addWidget(self.msg_label, 1)
        T = Ribbon.tiny
        h.addWidget(T("first", "First page", lambda: self.cur() and self.cur().goto(0)))
        h.addWidget(T("prev", "Previous page", lambda: self.cur() and self.cur().goto(self.cur().current_page() - 1)))
        self.page_spin = QSpinBox(minimum=1, maximum=1)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.editingFinished.connect(lambda: self.cur() and self.cur().goto(self.page_spin.value() - 1))
        h.addWidget(self.page_spin)
        self.page_total = QLabel("/ 0")
        h.addWidget(self.page_total)
        h.addWidget(T("next", "Next page", lambda: self.cur() and self.cur().goto(self.cur().current_page() + 1)))
        h.addWidget(T("last", "Last page", lambda: self.cur() and self.cur().goto(self.cur().doc.page_count - 1)))
        h.addStretch(1)
        h.addWidget(T("fit-width", "Fit width", lambda: self.cur() and self.cur().fit_width()))
        h.addWidget(T("fit-page", "Fit page (Ctrl+0)", lambda: self.cur() and self.cur().fit_page()))
        self.zoom_box = QComboBox(editable=True)
        self.zoom_box.addItems(ZOOMS)
        self.zoom_box.setFixedWidth(84)
        self.zoom_box.activated.connect(lambda _: self._zoom_text())
        self.zoom_box.lineEdit().returnPressed.connect(self._zoom_text)
        h.addWidget(self.zoom_box)
        h.addWidget(T("zoom-out", "Zoom out", lambda: self._zoom(0.8)))
        h.addWidget(T("zoom-in", "Zoom in", lambda: self._zoom(1.25)))
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
                        ("Ctrl+0", lambda: self.cur() and self.cur().fit_page()),
                        ("Ctrl+=", lambda: self._zoom(1.25)), ("Ctrl+-", lambda: self._zoom(0.8))):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            self.addAction(a)

    def _zoom(self, k):
        if self.cur():
            self.cur().set_zoom(self.cur().zoom * k)

    def _tab_changed(self, _=None):
        v = self.cur()
        if v:
            v.set_tool(self.tool)
        self.refresh_panels()
        self._status()
        self._title()

    def _title(self):
        v = self.cur()
        self.setWindowTitle("pdfdesk" + (f" — {os.path.basename(v.path or 'untitled')}{' *' if v.modified else ''}"
                                         if v else ""))
        if v:
            i = self.docs.currentIndex()
            self.docs.setTabText(i, os.path.basename(v.path or "untitled") + (" *" if v.modified else ""))

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
            dst = QFileDialog.getSaveFileName(self, "Save attachment", item.text())[0]
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
        else:
            self.page_spin.setMaximum(1)
            self.page_total.setText("/ 0")
        self.page_spin.blockSignals(False)

    def msg(self, text: str, ms: int = 5000):
        self.msg_label.setText(text)

    def error(self, title: str, e: Exception | str):
        QMessageBox.warning(self, title, str(e))

    # ---- ribbon construction (layout follows Foxit's tabs and groups) -------------------------------
    def _reg(self, label: str, fn):
        self.ribbon.register(label, fn)
        return fn

    def L(self, text, ic, fn, tip=None):
        self._reg(text, fn)
        return Ribbon.large(text, ic, fn, tip=tip)

    def S(self, text, ic, fn, tip=None):
        self._reg(text, fn)
        return Ribbon.small(text, ic, fn, tip=tip)

    def LM(self, text, ic, entries):
        for t, f in entries:
            self._reg(f"{text}: {t}", f)
        return Ribbon.large(text, ic, menu=entries)

    def TL(self, text, tool, ic=None):
        """Large checkable tool button."""
        self._reg(text, lambda t=tool: self.set_tool(t))
        b = Ribbon.large(text, ic or tool, lambda t=tool: self.set_tool(t), checkable=True, tip=TOOL_HINTS.get(tool))
        self.tool_buttons.setdefault(tool, []).append(b)
        return b

    def TS(self, text, tool, ic=None):
        self._reg(text, lambda t=tool: self.set_tool(t))
        b = Ribbon.small(text, ic or tool, lambda t=tool: self.set_tool(t), checkable=True, tip=TOOL_HINTS.get(tool))
        self.tool_buttons.setdefault(tool, []).append(b)
        return b

    def TI(self, tip, tool, ic=None):
        """Icon-only checkable tool button for grids."""
        self._reg(tip, lambda t=tool: self.set_tool(t))
        b = Ribbon.tiny(ic or tool, tip, lambda t=tool: self.set_tool(t), checkable=True)
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
        G("File", "Optimize", [LM("Reduce File Size", "optimize", [(f"{q.capitalize()} quality", lambda q=q: self.optimize(q))
                                                                    for q in ("high", "medium", "low", "minimum")]),
                               L("Audit Space Usage", "audit", self.audit_space)])

        # Home
        self.tools_group("Home")
        G("Home", "View", [L("Fit Width", "fit-width", lambda: self.cur() and self.cur().fit_width()),
                           L("Fit Page", "fit-page", lambda: self.cur() and self.cur().fit_page()),
                           stack(S("Zoom In", "zoom-in", lambda: self._zoom(1.25)),
                                 S("Zoom Out", "zoom-out", lambda: self._zoom(0.8)))])
        G("Home", "Find", [L("Advanced Search", "search-folder", self.folder_search)])
        G("Home", "Create", [L("From File", "create", self.create_from_file), L("Combine", "combine", self.combine_files)])
        G("Home", "Edit", [TL("Edit Text", "edit-text"), TL("Edit Object", "edit-object"), TL("Add Text", "add-text")])
        G("Home", "Review", [stack(self.TS("Highlight", "highlight"), self.TS("Note", "note"),
                                   self.TS("Typewriter", "typewriter")), stack(self._color_button())])
        G("Home", "Protect", [L("Sign", "sign", lambda: self.set_tool("sign-place")),
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
                                "Create links", lambda d: run("Links.Detect", d), "link(s) created")),
                                S("Remove All Links", "delete", lambda: self._count(
                                    "Remove links", lambda d: run("Links.Remove", d), "link(s) removed")))])
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
                                stack(S("Rotate Right", "rotate-r", lambda: self._pages_cmd("Pages.Rotate", angle=90)),
                                      S("Rotate Left", "rotate-l", lambda: self._pages_cmd("Pages.Rotate", angle=270)),
                                      S("Reverse", "reverse", lambda: self.apply("Reverse pages", lambda d: run("Pages.Reverse", d))))])
        G("Organize", "Bookmarks", [L("From Headings", "bookmarks", lambda: self.bookmark_command("from-headings", -1)),
                                    S("Add Bookmark", "bookmarks", lambda: self.bookmark_command("add", -1))])
        G("Organize", "Files", [L("Combine", "combine", self.combine_files), L("Split", "split", self.split)])
        G("Organize", "Page Layout", [stack(S("Crop White", "crop", lambda: self._pages_cmd("Pages.Crop", remove_white=True)),
                                            S("Flatten", "flatten", lambda: self.apply("Flatten", lambda d: run("Pages.Flatten", d))))])
        G("Organize", "Marks", [LM("Header & Footer", "header", [("Add…", self.header_footer),
                                    ("Remove all", lambda: self.apply("Remove header/footer", lambda d: run("Pages.RemoveHeaderFooter", d)))]),
                                LM("Watermark", "watermark", [("Add…", self.watermark),
                                    ("Remove all", lambda: self.apply("Remove watermark", lambda d: run("Pages.RemoveWatermark", d)))]),
                                LM("Background", "background", [("Add (cream)", lambda: self.apply("Background", lambda d: run("Pages.Background", d))),
                                    ("Remove", lambda: self.apply("Remove background", lambda d: run("Pages.RemoveBackground", d)))]),
                                L("Bates", "bates", self.bates)])

        # Comment — same groups as Foxit: Tools | Text Markup | Pin | Typewriter | Drawing | Stamp | Manage
        self.tools_group("Comment")
        G("Comment", "Text Markup", [grid([TI("Highlight", "highlight"), TI("Underline", "underline"),
                                           TI("Strikeout", "strikeout"), TI("Squiggly", "squiggly"),
                                           TI("Replace Text", "replace-text"), TI("Area Highlight", "area-highlight", "highlight")], 3)])
        G("Comment", "Pin", [TL("Note", "note"), TL("File", "file")])
        G("Comment", "Typewriter", [TL("Typewriter", "typewriter"), stack(self.TS("Callout", "callout"), self.TS("Textbox", "textbox"))])
        G("Comment", "Drawing", [grid([TI("Rectangle", "rectangle"), TI("Oval", "oval"), TI("Line", "line"),
                                       TI("Arrow", "arrow"), TI("Polygon", "polygon"), TI("Cloud", "cloud"),
                                       TI("Polyline", "polyline"), TI("Pencil", "pencil")], 4)])
        G("Comment", "Color", [stack(self._color_button())])
        stamp = QComboBox()
        stamp.addItems(STAMPS)
        stamp.setFixedWidth(120)
        stamp.currentTextChanged.connect(lambda t: setattr(self, "stamp_name", t))
        G("Comment", "Stamp", [TL("Stamp", "stamp"), stack(stamp)])
        G("Comment", "Manage", [L("Delete All", "delete-all", self.delete_all_comments)])

        # View
        self.tools_group("View")
        G("View", "Zoom", [L("Fit Width", "fit-width", lambda: self.cur() and self.cur().fit_width()),
                           L("Fit Page", "fit-page", lambda: self.cur() and self.cur().fit_page()),
                           stack(S("Zoom In", "zoom-in", lambda: self._zoom(1.25)), S("Zoom Out", "zoom-out", lambda: self._zoom(0.8)))])
        G("View", "Layers", [L("Layers", "layers", self.layers)])
        G("View", "Panels", [L("Navigation Panels", "navigation", self.toggle_nav, tip="Show or hide the navigation panels (F4)")])
        G("View", "Compare", [L("Compare", "compare", self.compare)])

        # Protect
        self.tools_group("Protect")
        pats = __import__("pdfdesk.commands.protect", fromlist=["x"]).PATTERNS
        G("Protect", "Redaction", [TL("Mark for Redaction", "redact"),
                                   L("Apply Redactions", "apply", self.apply_redactions),
                                   stack(S("Search & Redact", "search-redact", self.search_redact),
                                         Ribbon.small("Find Pattern", "pattern", menu=[(k, lambda k=k: self.pattern_redact(k)) for k in pats]),
                                         self.TS("Whiteout", "whiteout"))])
        G("Protect", "Security", [L("Password", "password", self.password), L("Remove Security", "unlock", self.remove_security),
                                  L("Remove Hidden Info", "hidden", lambda: self.apply("Remove hidden info", lambda d: run("Protect.RemoveHiddenInfo", d)))])
        G("Protect", "Sign & Certify", [TL("Sign", "digital-sign"), L("Certify", "certify", lambda: self.digital_sign(None, certify=True)),
                                        stack(S("Create ID", "id", self.create_id), S("Validate", "validate", self.validate))])

        # Form — Foxit's Form tab: Tools | Form Fields | Form Recognition | Form Data | Manage
        self.tools_group("Form")
        G("Form", "Form Fields", [grid([TI("Text Field", "field-text"), TI("Check Box", "field-check"),
                                        TI("Radio Button", "field-radio"), TI("Combo Box", "field-combo"),
                                        TI("List Box", "field-list"), TI("Push Button", "field-button"),
                                        TI("Signature Field", "field-sign")], 4)])
        G("Form", "Form Recognition", [L("Recognize Fields", "recognize", lambda: self._count(
            "Form field recognition", lambda d: len(run("Form.Recognize", d)), "field(s) created"))])
        G("Form", "Form Data", [L("Import", "import", self.form_import),
                                LM("Export", "export", [(f"{x.upper()} (.{x})", lambda x=x: self.form_export(x))
                                                        for x in ("fdf", "xfdf", "json", "csv")]),
                                L("Reset Form", "reset", lambda: self.apply("Reset form", lambda d: run("Form.Reset", d)))])
        G("Form", "Manage", [L("Calculate", "calc", self.form_calculate),
                             stack(S("Flatten Form", "flatten", lambda: self.apply("Flatten form", lambda d: run("Form.Flatten", d))),
                                   S("Delete All Fields", "delete-all", self.delete_all_fields))])

        for tab, what in NOT_YET.items():
            r.note(tab, f"{what} are planned for a later phase.")
        G("Help", "Help", [L("About", "help", lambda: QMessageBox.about(
            self, "pdfdesk", "pdfdesk — a PDF editor for Linux.\nBuilt on PyMuPDF, pikepdf, pyHanko, OCRmyPDF, Qt."))])

    def _saved_sig_menu(self):
        from PySide6.QtWidgets import QMenu
        b = Ribbon.large("Saved Signatures", "sign-place")
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
            m.addAction("(none saved yet)").setEnabled(False)

    def _use_signature(self, s: dict):
        self.sig_spec = s
        self.set_tool("sign-place")
        self.msg("Click or drag on the page to place: " + dialogs.describe_signature(s))

    # ---- comment colors ---------------------------------------------------------------------------------
    def _color_button(self):
        b = dialogs.ColorButton(text="Color")
        b.setToolTip("Color of new comments made with the current tool (Highlight when no comment tool is on)")
        b.setFixedHeight(22)
        b.changed.connect(self.set_tool_color)
        self.color_buttons.append(b)
        return b

    def _color_tool(self) -> str:
        return self.tool if self.tool in comment_cmds.DEFAULT_COLORS else "highlight"

    def set_tool_color(self, rgb):
        t = self._color_tool()
        if rgb:
            self.tool_colors[t] = tuple(rgb)
        QSettings("pdfdesk", "pdfdesk").setValue("tool_colors", json.dumps(self.tool_colors))
        self._show_tool_color()
        if self.cur():
            self.cur().viewport().update()
        self.msg(f"New {t.replace('-', ' ')} comments use this color")

    def _show_tool_color(self):
        t = self._color_tool()
        rgb = self.tool_colors.get(t) or comment_cmds.DEFAULT_COLORS[t]
        for b in self.color_buttons:
            b.set_color(rgb, emit=False)
            b.setText(f"{t.replace('-', ' ').capitalize()} color")

    def comment_properties(self, page: int, xref: int):
        v = self.cur()
        r = dialogs.CommentPropertiesDialog.ask(self, run("Comment.Style", v.doc, page, xref))
        if r:
            self.apply("Comment properties", lambda d: run("Comment.SetStyle", d, page, xref, **r))

    def _comment_command(self, name: str, page0: int, xref: int):
        v = self.cur()
        if not v:
            return
        self._focus_comment(page0, xref)
        if name == "properties":
            self.comment_properties(page0 + 1, xref)
        elif name == "delete":
            v.selected = None
            self.apply("Delete comment", lambda d: run("Comment.Delete", d, page0 + 1, xref))

    def _tab_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        i = self.docs.tabBar().tabAt(pos)
        v = self.docs.widget(i)
        if not isinstance(v, DocView):
            return
        self.docs.setCurrentIndex(i)
        m = QMenu(self)
        m.addAction("Save", self.save)
        m.addAction("Save As…", self.save_as)
        if v.path:
            m.addAction("Copy file path", lambda: QApplication.clipboard().setText(v.path))
            m.addAction("Open containing folder", lambda: subprocess.Popen(["xdg-open", os.path.dirname(v.path)]))
        m.addSeparator()
        m.addAction("Close", lambda: self.close_tab(self.docs.indexOf(v)))
        m.addAction("Close other tabs", lambda: [self.close_tab(self.docs.indexOf(w)) for w in
                                                  [self.docs.widget(k) for k in range(self.docs.count())]
                                                  if isinstance(w, DocView) and w is not v])
        m.exec(self.docs.tabBar().mapToGlobal(pos))

    # ---- tools ----------------------------------------------------------------------------------------
    def set_tool(self, tool: str):
        self.tool = tool
        for name, buttons in self.tool_buttons.items():
            for b in buttons:
                b.setChecked(name == tool)
        self._show_tool_color()
        for i in range(self.docs.count()):
            w = self.docs.widget(i)
            if isinstance(w, DocView):
                w.set_tool(tool)
        self.msg(TOOL_HINTS.get(tool, ""), 8000)

    def on_tool(self, a: dict):
        v = self.cur()
        if not v:
            return
        t, page = a["tool"], a.get("page")
        if t == "set-tool":
            return self.set_tool(a["name"])
        if t == "page-command":
            return self._page_command(a["name"], a["pages"])
        if t in ("move-annot", "delete-annot", "edit-annot", "edit-text-commit", "sign-place", "annot-rect",
                 "object-rect", "delete-object", "annot-style") or t not in (
                "select", "hand", "zoom"):
            if getattr(v, "readonly", False):
                return self.error("Read only", "This document was opened with its user password and does not "
                                  "allow changes. Open it with the permissions password to edit.")
        au = self.author
        col = a.get("color") or self.tool_colors.get(t)
        cw = {"color": col} if col else {}
        try:
            if t == "delete-annot":
                return self.apply("Delete comment", lambda d: run("Comment.Delete", d, page, a["xref"]))
            if t == "annot-rect":
                return self.apply("Resize comment", lambda d: run("Comment.SetRect", d, page, a["xref"], a["rect"]))
            if t == "object-rect":
                return self.apply("Move object", lambda d: run("Object.Transform", d, page, a["index"], a["rect"]))
            if t == "delete-object":
                return self.apply("Delete object", lambda d: run("Object.Delete", d, page, a["index"]))
            if t == "move-annot":
                return self.apply("Move comment", lambda d: run("Comment.Move", d, page, a["xref"], a["dx"], a["dy"]))
            if t == "edit-annot":
                return self.comment_properties(page, a["xref"])
            if t == "annot-style":
                return self.apply("Comment properties", lambda d: run("Comment.SetStyle", d, page, a["xref"], **a["style"]))
            if t in ("highlight", "underline", "strikeout", "squiggly"):
                name = {"highlight": "Highlight", "underline": "Underline", "strikeout": "Strikeout",
                        "squiggly": "Squiggly"}[t]
                return self.apply(name, lambda d: run(f"Comment.{name}", d, page, a["start"], a["stop"], author=au, **cw))
            if t == "replace-text":
                r = dialogs.TextDialog.ask(self, "Replace text", "Replacement text:")
                return r and self.apply("Replace text", lambda d: run("Comment.ReplaceText", d, page, a["start"], a["stop"], r, author=au))
            if t == "note":
                r = dialogs.TextDialog.ask(self, "Note", "Note text:")
                return r and self.apply("Note", lambda d: run("Comment.Note", d, page, a["point"], r, author=au, **cw))
            if t == "file":
                p = QFileDialog.getOpenFileName(self, "Attach file")[0]
                return p and self.apply("Attach file", lambda d: run("Comment.File", d, page, a["point"], p, author=au))
            if t == "typewriter":
                r = dialogs.TextDialog.ask(self, "Typewriter", "Text:", size=12)
                return r and self.apply("Typewriter", lambda d: run("Comment.Typewriter", d, page, a["point"], r[0], fontsize=r[1], author=au, **cw))
            if t == "add-text":
                r = dialogs.TextDialog.ask(self, "Add text", "Text:", size=12)
                return r and self.apply("Add text", lambda d: run("Text.Add", d, page, a["point"], r[0], fontsize=r[1]))
            if t == "textbox" and a["rect"]:
                r = dialogs.TextDialog.ask(self, "Text box", "Text:")
                return r and self.apply("Text box", lambda d: run("Comment.Textbox", d, page, a["rect"], r, author=au))
            if t == "callout":
                r = dialogs.TextDialog.ask(self, "Callout", "Text:")
                box = pymupdf.Rect(a["stop"].x, a["stop"].y, a["stop"].x + 140, a["stop"].y + 50)
                return r and self.apply("Callout", lambda d: run("Comment.Callout", d, page, a["start"], box, r, author=au))
            if t in ("rectangle", "oval", "area-highlight") and a["rect"]:
                name = {"rectangle": "Rectangle", "oval": "Oval", "area-highlight": "AreaHighlight"}[t]
                return self.apply(name, lambda d: run(f"Comment.{name}", d, page, a["rect"], author=au, **cw))
            if t in ("line", "arrow"):
                name = "Line" if t == "line" else "Arrow"
                return self.apply(name, lambda d: run(f"Comment.{name}", d, page, a["start"], a["stop"], author=au, **cw))
            if t in ("polygon", "cloud", "polyline"):
                name = {"polygon": "Polygon", "cloud": "Cloud", "polyline": "Polyline"}[t]
                return self.apply(name, lambda d: run(f"Comment.{name}", d, page, a["points"], author=au, **cw))
            if t == "pencil":
                return self.apply("Pencil", lambda d: run("Comment.Pencil", d, page, a["strokes"], author=au, **cw))
            if t == "stamp" and a["rect"]:
                return self.apply("Stamp", lambda d: run("Comment.Stamp", d, page, a["rect"], self.stamp_name, author=au))
            if t == "redact" and a["rect"]:
                return self.apply("Mark for redaction", lambda d: run("Redact.MarkRects", d, page, [a["rect"]]))
            if t == "whiteout" and a["rect"]:
                return self.apply("Whiteout", lambda d: run("Redact.Whiteout", d, page, [a["rect"]]))
            if t == "edit-text-commit":
                return self.apply("Edit text", lambda d: run("Text.EditLine", d, page, a["point"], a["text"]))
            if t == "image":
                if not a["rect"]:
                    return
                p = QFileDialog.getOpenFileName(self, "Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)")[0]
                return p and self.apply("Add image", lambda d: run("Sign.Image", d, page, a["rect"], path=p))
            if t == "sign-place":
                return self._place_signature(a)
            if t == "fill-field":
                return self.fill_field(page, a["xref"])
            if t.startswith("field-") and a["rect"]:
                return self.add_field(t[6:], page, a["rect"])
            if t == "link" and a["rect"]:
                return self.add_link(page, a["rect"])
            if t == "digital-sign" and a["rect"]:
                return self.digital_sign(a)
        except Exception as e:  # noqa: BLE001
            self.error("Error", e)

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
        placed = self.apply("Signature", go)
        if placed is not None:          # select it, so it can be moved or resized right away
            self.set_tool("edit-object")
            self.cur().select_object_at(page - 1, placed.tl + (placed.br - placed.tl) / 2)
            self.msg("Signature placed. Drag to move it, drag a corner to resize, Delete removes it.", 8000)

    # ---- applying edits ----------------------------------------------------------------------------
    def apply(self, label: str, fn):
        """Run fn(doc) as one undoable step. A failure restores the document and shows the error."""
        v = self.cur()
        if not v:
            return
        if getattr(v, "readonly", False):
            return self.error("Read only", "This document does not allow changes.")
        v.checkpoint(label)
        try:
            res = fn(v.doc)
        except Exception as e:  # noqa: BLE001
            v.rollback()
            v.modified = bool(v.undo_stack) or v.modified
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
        if v and (l := v.undo()):
            self._after(v)
            self.msg(f"Undid: {l}")

    def redo(self):
        v = self.cur()
        if v and (l := v.redo()):
            self._after(v)
            self.msg(f"Redid: {l}")

    # ---- open / save / close -----------------------------------------------------------------------------
    def _wire(self, v: DocView):
        v.tool_colors = self.tool_colors
        v.toolAction.connect(self.on_tool)
        v.pageChanged.connect(lambda n: self._status())
        v.changed.connect(self._title)

    def open_path(self, path: str) -> DocView | None:
        try:
            doc = pymupdf.open(path)
        except Exception as e:  # noqa: BLE001
            self.error("Open", e)
            return None
        pw, auth = None, 0
        if doc.needs_pass:
            for _ in range(3):
                pw, ok = QInputDialog.getText(self, "Password", f"Password for {os.path.basename(path)}:",
                                              QLineEdit.Password)
                if not ok:
                    return None
                auth = doc.authenticate(pw)
                if auth:
                    break
                QMessageBox.warning(self, "Password", "That password is not correct.")
            else:
                return None
        v = DocView(doc, path, pw)
        v.security = sec.from_open(doc, pw, auth)
        v.readonly = sec.restricted(doc, auth)
        if v.readonly:
            QMessageBox.information(self, "Restricted", "This file was opened with its user password and does not "
                                    "allow changes. You can read and print it but not edit it.")
        self._add(v, os.path.basename(path))
        add_recent(path)
        self.start.refresh()
        return v

    def _add(self, v: DocView, title: str):
        self._wire(v)
        if not hasattr(v, "security"):
            v.security, v.readonly = None, False
        self.docs.setCurrentIndex(self.docs.addTab(v, title))
        QTimer.singleShot(0, v.fit_width)      # after the splitter and panels have their final size
        self._tab_changed()

    def new_doc(self, doc: pymupdf.Document, name: str):
        v = DocView(doc, None)
        v.security, v.readonly, v.modified = None, False, True
        self._add(v, name)

    def open_dialog(self):
        for p in QFileDialog.getOpenFileNames(self, "Open", "", "PDF (*.pdf);;All files (*)")[0]:
            self.open_path(p)

    def close_tab(self, i):
        v = self.docs.widget(i)
        if not isinstance(v, DocView):
            return
        if v.modified:
            r = QMessageBox.question(self, "Close", f"Save changes to {os.path.basename(v.path or 'untitled')}?",
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
                e.ignore()
                return
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
        p = QFileDialog.getSaveFileName(self, "Save As", v.path or "untitled.pdf", "PDF (*.pdf)")[0]
        return bool(p) and self._save_to(v, p, incremental=False)

    def _save_to(self, v: DocView, path: str, incremental: bool) -> bool:
        v._commit_editor()          # a text edit still open in the page counts
        s = v.security
        try:
            if s is not None and not s.complete:
                if v.readonly:
                    return self.error("Save", "This document is read only.") or False
                if s.owner_pw is not None and s.user_pw is None:
                    pw, ok = QInputDialog.getText(self, "Open password", "Enter the document's open password to "
                                                  "keep it protected (leave empty for none):", QLineEdit.Password)
                    if not ok:
                        return False
                    s.user_pw = pw
                elif s.user_pw is not None and s.owner_pw is None:
                    pw, ok = QInputDialog.getText(self, "Permissions password", "Enter the permissions password to "
                                                  "keep it protected:", QLineEdit.Password)
                    if not ok or not pw:
                        return False
                    s.owner_pw = pw
            same = v.doc.name == path
            v.doc = sec.save(v.doc, path, s, incremental and same)
        except Exception as e:  # noqa: BLE001
            self.error("Save", e)
            return False
        v.path, v.modified = path, False
        v.undo_stack.clear() if not incremental else None
        add_recent(path)
        self.start.refresh()
        v.relayout()
        self._title()
        self.refresh_panels()
        self.msg(f"Saved {path}")
        return True

    def print_doc(self):
        v = self.cur()
        if not v:
            return
        out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True).stdout.split()
        if not out:
            return self.error("Print", "No printers are configured (CUPS).")
        name, ok = QInputDialog.getItem(self, "Print", "Printer:", out, 0, False)
        if not ok:
            return
        n, ok = QInputDialog.getInt(self, "Print", "Copies:", 1, 1, 99)
        if not ok:
            return
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(v.doc.tobytes())
        r = subprocess.run(["lp", "-d", name, "-n", str(n), f.name], capture_output=True, text=True)
        self.msg(r.stdout.strip() or r.stderr.strip())

    # ---- find / panels --------------------------------------------------------------------------------
    def do_find(self):
        v = self.cur()
        if v:
            self.msg(f"{v.find(self.find_box.text())} matches")

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

    def _pages_cmd(self, name, **kw):
        self.apply(name.split(".")[-1], lambda d: run(name, d, pages=self._sel_spec(), **kw))

    def delete_pages(self):
        v = self.cur()
        spec = self._sel_spec()
        if v and QMessageBox.question(self, "Delete pages", f"Delete page(s) {spec}?") == QMessageBox.Yes:
            self.apply("Delete pages", lambda d: run("Pages.Delete", d, pages=spec))

    def extract_pages(self):
        v = self.cur()
        if not v:
            return
        spec, ok = QInputDialog.getText(self, "Extract pages", "Pages (e.g. 1-3,7):", text=self._sel_spec())
        if not ok or not spec:
            return
        try:
            out = run("Pages.Extract", v.doc, pages=spec)
        except Exception as e:  # noqa: BLE001
            return self.error("Extract", e)
        self.new_doc(out, f"extract-{spec}.pdf")

    def insert_blank(self):
        v = self.cur()
        if v:
            sel = self.thumbs.selected_pages()
            after = (sel[-1] + 1) if sel else v.current_page() + 1
            r = v.doc[min(after, v.doc.page_count) - 1].rect
            self.apply("Insert blank page", lambda d: run("Pages.InsertBlank", d, after, r.width, r.height))

    def insert_file(self, after: int | None = None):
        v = self.cur()
        p = QFileDialog.getOpenFileName(self, "Insert pages from", "", "PDF (*.pdf)")[0]
        if v and p:
            sel = self.thumbs.selected_pages()
            at = after if after is not None else ((sel[-1] + 1) if sel else v.current_page() + 1)
            self.apply("Insert pages", lambda d: run("Pages.InsertFile", d, p, at))

    def _reorder(self, order: list[int]):
        self.apply("Reorder pages", lambda d: d.select(order))

    def _page_command(self, name: str, pages: list[int]):
        v = self.cur()
        if not v or not pages:
            return
        spec = _ranges(pages)
        if name == "rotate-right":
            self.apply("Rotate", lambda d: run("Pages.Rotate", d, 90, spec))
        elif name == "rotate-left":
            self.apply("Rotate", lambda d: run("Pages.Rotate", d, 270, spec))
        elif name == "delete":
            if QMessageBox.question(self, "Delete pages", f"Delete page(s) {spec}?") == QMessageBox.Yes:
                self.apply("Delete pages", lambda d: run("Pages.Delete", d, spec))
        elif name == "extract":
            self.new_doc(run("Pages.Extract", v.doc, spec), f"extract-{spec}.pdf")
        elif name == "duplicate":
            def dup(d):
                for k, i in enumerate(pages):
                    d.fullcopy_page(i + k, pages[-1] + 1 + k)
            self.apply("Duplicate pages", dup)
        elif name == "insert-blank":
            r = v.doc[pages[-1]].rect
            self.apply("Insert blank page", lambda d: run("Pages.InsertBlank", d, pages[-1] + 1, r.width, r.height))
        elif name == "insert-file":
            self.insert_file(pages[-1] + 1)

    def split(self):
        v = self.cur()
        if not v:
            return
        dlg = dialogs.SplitDialog(self, bool([t for t in v.doc.get_toc() if t[0] == 1]))
        if dlg.exec() != QDialog.Accepted:
            return
        out = QFileDialog.getExistingDirectory(self, "Output folder")
        if not out:
            return
        parts = run("Pages.Split", v.doc, **dlg.values())
        base = os.path.splitext(os.path.basename(v.path or "document"))[0]
        for k, (name, d) in enumerate(parts, 1):
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
            d.save(os.path.join(out, f"{base}_{k:02d}_{safe}.pdf"), garbage=3, deflate=True)
        self.msg(f"Wrote {len(parts)} files to {out}")

    def combine_files(self):
        ps = QFileDialog.getOpenFileNames(self, "Combine files", "", "All supported files (*)")[0]
        if ps:
            try:
                self.new_doc(run("Convert.Combine", ps), "combined.pdf")
            except Exception as e:  # noqa: BLE001
                self.error("Combine", e)

    def header_footer(self, bates=False):
        d = dialogs.HeaderFooterDialog(self, bates)
        if d.exec() == QDialog.Accepted:
            kw = d.values()
            self.apply("Bates numbering" if bates else "Header & footer", lambda doc: run("Pages.HeaderFooter", doc, **kw))

    def bates(self):
        self.header_footer(bates=True)

    def watermark(self):
        d = dialogs.WatermarkDialog(self)
        if d.exec() == QDialog.Accepted:
            kw = d.values()
            self.apply("Watermark", lambda doc: run("Pages.Watermark", doc, **kw))

    def delete_all_comments(self):
        if self.cur() and QMessageBox.question(self, "Delete comments", "Delete all comments?") == QMessageBox.Yes:
            def go(d):
                for c in run("Comment.List", d):
                    run("Comment.Delete", d, c["page"], c["xref"])
            self.apply("Delete all comments", go)

    # ---- edit ----------------------------------------------------------------------------------------------
    def find_replace(self):
        v = self.cur()
        if not v:
            return
        f, ok = QInputDialog.getText(self, "Replace", "Find:", text=self.find_box.text())
        if not ok or not f:
            return
        r, ok = QInputDialog.getText(self, "Replace", f"Replace “{f}” with:")
        if not ok:
            return
        n = self.apply("Replace text", lambda d: run("Text.Replace", d, f, r))
        if n is not None:
            self.msg(f"{n} replacement(s)")

    def properties(self):
        v = self.cur()
        if not v:
            return
        d = dialogs.PropertiesDialog(self, v.doc, v.path)
        if d.exec() == QDialog.Accepted:
            vals = d.values()
            self.apply("Properties", lambda doc: doc.set_metadata({**(doc.metadata or {}), **vals}))

    def _count(self, label: str, fn, what: str):
        n = self.apply(label, fn)
        if n is not None:
            self.msg(f"{n} {what}")

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
            value, ok = QInputDialog.getItem(self, f["name"], f"{f['name']}:", opts, cur, kind == "combo")
            if not ok:
                return
        elif kind == "text":
            value, ok = QInputDialog.getMultiLineText(self, f["name"], f"{f['name']}:", f["value"] or "")
            if not ok:
                return
        elif kind == "signature":
            return self.digital_sign({"tool": "digital-sign", "page": page, "rect": pymupdf.Rect(f["rect"]),
                                      "field": f["name"]})
        else:
            return
        self.apply(f"Fill {f['name']}", lambda d: run("Form.SetField", d, page, xref, value))

    def add_field(self, kind: str, page: int, rect):
        kinds = {"text": "text", "check": "checkbox", "radio": "radio", "combo": "combo", "list": "list",
                 "button": "button", "sign": "signature"}
        k = kinds[kind]
        kw = {}
        if k == "radio":
            groups = sorted({f["name"] for f in run("Form.List", self.cur().doc) if f["type"] == "radio"}) or ["Group1"]
            g, ok = QInputDialog.getItem(self, "Radio button", "Group (buttons in one group exclude each other):",
                                         groups, len(groups) - 1, True)
            if not ok or not g:
                return
            c, ok = QInputDialog.getText(self, "Radio button", "This button's value:", text="Choice")
            if not ok or not c:
                return
            kw = {"group": g, "name": c}
        else:
            name, ok = QInputDialog.getText(self, "New field", "Field name:")
            if not ok:
                return
            kw["name"] = name or None
            if k in ("combo", "list"):
                o, ok = QInputDialog.getText(self, "Options", "Options, separated by commas:", text="Option 1, Option 2")
                if not ok:
                    return
                kw["options"] = [x.strip() for x in o.split(",") if x.strip()]
            if k == "text" and rect.height > 40:
                kw["multiline"] = True
        self.apply(f"Add {k} field", lambda d: run("Form.AddField", d, page, rect, k, **kw))

    def form_import(self):
        p = QFileDialog.getOpenFileName(self, "Import form data", "", "Form data (*.fdf *.xfdf *.json *.csv)")[0]
        if p:
            self._count("Import form data", lambda d: run("Form.Import", d, p), "field(s) filled")

    def form_export(self, ext: str):
        v = self.cur()
        if not v:
            return
        base = os.path.splitext(v.path or "form.pdf")[0] + f".{ext}"
        p = QFileDialog.getSaveFileName(self, "Export form data", base, f"{ext.upper()} (*.{ext})")[0]
        if p:
            try:
                n = len(run("Form.Export", v.doc, p, source=os.path.basename(v.path or "form.pdf")))
                self.msg(f"{n} field(s) exported to {p}")
            except Exception as e:  # noqa: BLE001
                self.error("Export form data", e)

    def form_calculate(self):
        v = self.cur()
        if not v:
            return
        names = sorted({f["name"] for f in run("Form.List", v.doc) if f["type"] == "text"})
        if len(names) < 2:
            return self.error("Calculate", "The form needs at least two text fields.")
        target, ok = QInputDialog.getItem(self, "Calculate", "Result field:", names, 0, False)
        if not ok:
            return
        src, ok = QInputDialog.getText(self, "Calculate", "Fields to combine, separated by commas:",
                                       text=", ".join(n for n in names if n != target))
        if not ok:
            return
        op, ok = QInputDialog.getItem(self, "Calculate", "Operation:", ["sum", "product", "average", "min", "max"], 0, False)
        if ok:
            r = self.apply("Calculate", lambda d: run("Form.Calculate", d, target,
                                                     [x.strip() for x in src.split(",") if x.strip()], op))
            if r is not None:
                self.msg(f"{target} = {r:g}")

    def delete_all_fields(self):
        v = self.cur()
        if v and QMessageBox.question(self, "Delete fields", "Delete every form field?") == QMessageBox.Yes:
            self.apply("Delete all fields", lambda d: run("Form.DeleteField", d, [f["name"] for f in run("Form.List", d)]))

    # ---- links, bookmarks, layers ------------------------------------------------------------------------------
    def add_link(self, page: int, rect):
        v = self.cur()
        kind, ok = QInputDialog.getItem(self, "Create link", "Link to:", ["Web address", "Page in this document",
                                                                          "Another file"], 0, False)
        if not ok:
            return
        if kind == "Web address":
            url, ok = QInputDialog.getText(self, "Create link", "URL:", text="https://")
            if ok and url:
                self.apply("Add link", lambda d: run("Links.AddUrl", d, page, rect, url))
        elif kind == "Page in this document":
            n, ok = QInputDialog.getInt(self, "Create link", "Go to page:", v.current_page() + 1, 1, v.doc.page_count)
            if ok:
                self.apply("Add link", lambda d: run("Links.AddPage", d, page, rect, n))
        else:
            p = QFileDialog.getOpenFileName(self, "Link to file")[0]
            if p:
                self.apply("Add link", lambda d: run("Links.AddFile", d, page, rect, p))

    def bookmark_command(self, what: str, k: int):
        v = self.cur()
        if not v:
            return
        here = v.current_page() + 1
        toc = v.doc.get_toc()
        if what == "from-headings":
            if toc and QMessageBox.question(self, "Bookmarks", "Replace the existing bookmarks?") != QMessageBox.Yes:
                return
            return self._count("Bookmarks from headings", lambda d: run("Bookmarks.FromHeadings", d), "bookmark(s) created")
        if what in ("add", "add-child"):
            t, ok = QInputDialog.getText(self, "Add bookmark", "Title:", text=f"Page {here}")
            if not ok or not t:
                return
            if k < 0:
                return self.apply("Add bookmark", lambda d: run("Bookmarks.Add", d, t, here))
            lvl = toc[k][0] + (1 if what == "add-child" else 0)
            end = k + 1
            while end < len(toc) and toc[end][0] > toc[k][0]:
                end += 1
            return self.apply("Add bookmark", lambda d: run("Bookmarks.Add", d, t, here, level=lvl,
                                                            index=k + 1 if what == "add-child" else end))
        if what == "rename":
            t, ok = QInputDialog.getText(self, "Rename bookmark", "Title:", text=toc[k][1])
            return ok and t and self.apply("Rename bookmark", lambda d: run("Bookmarks.Rename", d, k, t))
        if what == "set-page":
            return self.apply("Bookmark destination", lambda d: run("Bookmarks.SetPage", d, k, here))
        if what in ("promote", "demote"):
            return self.apply(what.capitalize(), lambda d: run("Bookmarks.Indent", d, k, -1 if what == "promote" else 1))
        if what == "delete":
            return self.apply("Delete bookmark", lambda d: run("Bookmarks.Delete", d, k))

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
            self.apply("Layers", go)

    # ---- optimize and search ------------------------------------------------------------------------------------
    def optimize(self, quality: str):
        v = self.cur()
        if not v:
            return
        before = len(v.doc.tobytes(garbage=4, deflate=True))
        if self.apply(f"Reduce file size ({quality})", lambda d: run("Optimize.Reduce", d, quality)) is None and \
                not v.undo_stack:
            return
        after = len(v.doc.tobytes(garbage=4, deflate=True))
        self.msg(f"Estimated size {before / 1e6:.2f} MB → {after / 1e6:.2f} MB. Save to write it.", 10000)

    def audit_space(self):
        v = self.cur()
        if v:
            a = run("Optimize.Audit", v.doc)
            total = sum(a.values()) or 1
            QMessageBox.information(self, "Audit Space Usage", "\n".join(
                f"{k}: {n / 1024:,.0f} KB ({n * 100 / total:.0f}%)" for k, n in a.items()))

    def folder_search(self):
        def open_hit(path, page):
            for i in range(self.docs.count()):
                w = self.docs.widget(i)
                if isinstance(w, DocView) and w.path == path:
                    self.docs.setCurrentIndex(i)
                    break
            else:
                w = self.open_path(path)
            if w:
                w.goto(page - 1)
                w.find(dlg.text.text())
        dlg = dialogs.FolderSearchDialog(self, open_hit)
        dlg.show()
        self._search_dlg = dlg

    # ---- protect ----------------------------------------------------------------------------------------------
    def search_redact(self):
        t, ok = QInputDialog.getText(self, "Search & Redact", "Text to mark for redaction:")
        if ok and t:
            n = self.apply("Search & redact", lambda d: run("Redact.Search", d, needle=t))
            if n is not None:
                self.msg(f"{n} item(s) marked — use Apply to remove them permanently")

    def pattern_redact(self, kind: str):
        n = self.apply(f"Redact {kind}", lambda d: run("Redact.Search", d, kind=kind))
        if n is not None:
            self.msg(f"{n} item(s) marked — use Apply to remove them permanently")

    def apply_redactions(self):
        v = self.cur()
        if not v:
            return
        n = sum(1 for p in v.doc for a in (p.annots(types=[pymupdf.PDF_ANNOT_REDACT]) or []))
        if not n:
            return self.msg("Nothing is marked for redaction")
        if QMessageBox.warning(self, "Apply redactions", f"Permanently remove {n} marked item(s)? This cannot be "
                               "undone after saving.", QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok:
            self.apply("Apply redactions", lambda d: run("Redact.Apply", d))

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
            self.msg("Password protection will be applied when you save")

    def remove_security(self):
        v = self.cur()
        if v and v.security:
            if v.readonly:
                return self.error("Security", "Open the document with its permissions password first.")
            v.security = None
            v.modified = True
            self._title()
            self.msg("Security will be removed when you save")

    def create_id(self):
        p = dialogs.CreateIDDialog.ask(self, self.author)
        if p:
            self.msg(f"Digital ID saved: {p}")

    def create_signature(self):
        s = dialogs.SignatureDialog.ask(self, self.author)
        if s:
            self._use_signature(s)

    def digital_sign(self, a: dict | None, certify: bool = False):
        v = self.cur()
        if not v:
            return
        if v.security:
            return self.error("Sign", "Remove password protection before signing; sign, then protect a copy.")
        vals = dialogs.DigitalSignDialog.ask(self, certify, self.author)
        if not vals:
            return
        page = a["page"] if a else None
        field = a.get("field") if a else None
        rect = a["rect"] if a and not vals["invisible"] and not field else None
        if rect is None and not vals["invisible"] and not certify and a is None:
            vals["invisible"] = True
        base = os.path.splitext(v.path or "document.pdf")[0] + ("_certified.pdf" if vals["certify"] else "_signed.pdf")
        dst = QFileDialog.getSaveFileName(self, "Save signed copy", base, "PDF (*.pdf)")[0]
        if not dst:
            return
        try:
            run("Sign.Digital", v.doc.tobytes(), dst, vals["pfx"], vals["password"], page=page, rect=rect,
                reason=vals["reason"], location=vals["location"], certify=vals["certify"], field_name=field)
        except Exception as e:  # noqa: BLE001
            return self.error("Sign", e)
        self.open_path(dst)
        self.msg("Signed. Further edits to a signed file invalidate the signature unless saved incrementally.")

    def validate(self):
        v = self.cur()
        if not v or not v.path:
            return self.error("Validate", "Save the document first.")
        from .dialogs import IDS
        certs = sorted(glob.glob(str(IDS / "*.cer")))
        try:
            res = run("Sign.Validate", v.path, trusted_certs=certs)
        except Exception as e:  # noqa: BLE001
            return self.error("Validate", e)
        if not res:
            return QMessageBox.information(self, "Signatures", "This document has no digital signatures.")
        lines = []
        for r in res:
            state = "VALID" if r["valid"] and r["intact"] else "INVALID"
            lines.append(f"{r['field']}: {state}\n  Signer: {r['signer']}\n  Trusted: {'yes (your own ID)' if r['trusted'] else 'no'}\n"
                         f"  Covers: {r['coverage']}   Changes after signing: {r['modification_level']}")
        QMessageBox.information(self, "Signatures", "\n\n".join(lines))

    # ---- compare ----------------------------------------------------------------------------------------------
    def compare(self):
        v = self.cur()
        if not v:
            return
        p = QFileDialog.getOpenFileName(self, "Compare current document (old) with… (new)", "", "PDF (*.pdf)")[0]
        if not p:
            return
        try:
            res, changes = run("Compare.Run", v.doc, pymupdf.open(p))
        except Exception as e:  # noqa: BLE001
            return self.error("Compare", e)
        self.new_doc(res, "comparison.pdf")
        self.msg(f"{len(changes)} change(s) found")

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

    def create_from_file(self):
        p = QFileDialog.getOpenFileName(self, "Create PDF from file")[0]
        if p:
            self.msg("Converting…")
            QApplication.processEvents()
            try:
                self.new_doc(run("Convert.FromFile", p), os.path.splitext(os.path.basename(p))[0] + ".pdf")
            except Exception as e:  # noqa: BLE001
                self.error("Create PDF", e)

    def export(self, fmt: str):
        v = self.cur()
        if not v:
            return
        base = os.path.splitext(os.path.basename(v.path or "document"))[0]
        try:
            if fmt in ("png", "jpg", "tiff"):
                out = QFileDialog.getExistingDirectory(self, "Folder for images")
                if not out:
                    return
                n = len(run("Convert.ToImages", v.doc, out, fmt=fmt))
                return self.msg(f"Wrote {n} image(s) to {out}")
            ext = {"docx": "docx", "xlsx": "xlsx", "pptx": "pptx", "rtf": "rtf", "txt": "txt", "html": "html"}[fmt]
            out = QFileDialog.getSaveFileName(self, "Export", f"{base}.{ext}")[0]
            if not out:
                return
            self.msg("Exporting…")
            QApplication.processEvents()
            if fmt == "docx":
                run("Convert.ToWord", self._current_file(), out)
            elif fmt == "rtf":
                run("Convert.ToRtf", self._current_file(), out)
            elif fmt == "xlsx":
                run("Convert.ToExcel", v.doc, out)
            elif fmt == "pptx":
                run("Convert.ToPowerPoint", v.doc, out)
            elif fmt == "txt":
                run("Convert.ToText", v.doc, out)
            else:
                run("Convert.ToHtml", v.doc, out)
            self.msg(f"Exported {out}")
        except Exception as e:  # noqa: BLE001
            self.error("Export", e)

    def ocr(self):
        v = self.cur()
        if not v:
            return
        langs, ok = QInputDialog.getText(self, "OCR", "Languages (Tesseract codes, e.g. eng+deu+ara):", text="eng")
        if not ok or not langs.strip():
            return
        kinds = ["Editable text — replace the scan with real text you can edit",
                 "Searchable text — keep the image, add an invisible text layer"]
        kind, ok = QInputDialog.getItem(self, "OCR", "Output:", kinds, 0, False)
        if not ok:
            return
        self.msg("Running OCR…")
        QApplication.processEvents()
        language_list = [x for x in langs.replace(",", "+").split("+") if x.strip()]
        if kind == kinds[0]:
            res = self.apply("OCR (editable text)", lambda d: run("Ocr.Editable", d, languages=language_list))
            if isinstance(res, dict):
                self.msg(f"OCR done: {res['pages']} page(s), {res['lines']} lines, "
                         f"{len(res['suspects'])} uncertain word(s) to check")
            return
        try:
            src = self._current_file()
            out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
            run("Ocr.Run", src, out, languages=language_list)
            with open(out, "rb") as f:
                new = pymupdf.open("pdf", f.read())
        except Exception as e:  # noqa: BLE001
            return self.error("OCR", e)
        self.apply("OCR", lambda d: new)

    def to_pdfa(self):
        v = self.cur()
        if not v:
            return
        out = QFileDialog.getSaveFileName(self, "Save PDF/A copy", (os.path.splitext(v.path or "document")[0]) + "_pdfa.pdf",
                                          "PDF (*.pdf)")[0]
        if out:
            self.msg("Converting to PDF/A…")
            QApplication.processEvents()
            try:
                run("Convert.ToPDFA", self._current_file(), out)
                self.open_path(out)
            except Exception as e:  # noqa: BLE001
                self.error("PDF/A", e)


def launch(argv):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("pdfdesk")
    app.setDesktopFileName("pdfdesk")
    app.setWindowIcon(app_icon())
    w = Main()
    for a in argv:
        if a.lower().endswith(".pdf") and os.path.exists(a):
            w.open_path(a)
    w.show()

    def open_handed(paths):
        for p in paths:
            if os.path.exists(p):
                w.open_path(p)
        if w.isMinimized():
            w.showNormal()
        w.raise_()
        w.activateWindow()
    from .. import instance
    w._instance_server = instance.serve(open_handed)
    return app.exec()
