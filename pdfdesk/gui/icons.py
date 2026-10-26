"""Icons drawn in code (no image files): simple, flat, one accent colour per command family."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

ACCENT = "#6b2d7b"      # purple, like the File tab
BLUE, RED, GREEN, ORANGE, GRAY, YELLOW = "#2b6cc4", "#d33a3a", "#2e9e5b", "#e8872a", "#6b6f76", "#f1c40f"

# kind -> (glyph, colour) for glyph icons
GLYPHS = {
    "open": ("📂", ORANGE), "save": ("💾", BLUE), "print": ("🖨", GRAY), "mail": ("✉", BLUE), "close": ("✕", GRAY),
    "undo": ("↶", GRAY), "redo": ("↷", GRAY), "hand": ("✋", GRAY), "select": ("I", GRAY), "zoom": ("🔍", GRAY),
    "fit-width": ("↔", BLUE), "fit-page": ("⛶", BLUE), "zoom-in": ("+", BLUE), "zoom-out": ("−", BLUE),
    "highlight": ("H", YELLOW), "underline": ("U", GREEN), "strikeout": ("S", RED), "squiggly": ("~", BLUE),
    "replace-text": ("R", ORANGE), "note": ("🗒", YELLOW), "file": ("📎", GRAY), "typewriter": ("T", BLUE),
    "textbox": ("A", BLUE), "callout": ("💬", BLUE), "stamp": ("★", RED), "pencil": ("✎", ORANGE),
    "edit-text": ("T", BLUE), "edit-object": ("⬚", BLUE), "add-text": ("T+", BLUE), "image": ("🖼", GREEN), "replace": ("⇄", BLUE),
    "properties": ("ⓘ", GRAY), "sign": ("✍", BLUE), "sign-place": ("✍", BLUE), "digital-sign": ("🔏", GREEN),
    "certify": ("✔", GREEN), "validate": ("✔", GREEN), "id": ("🪪", GRAY), "redact": ("▮", RED),
    "whiteout": ("▯", GRAY), "apply": ("✔", RED), "search-redact": ("🔍", RED), "pattern": ("#", RED),
    "password": ("🔒", ORANGE), "unlock": ("🔓", ORANGE), "hidden": ("🧹", GRAY),
    "rotate-r": ("⟳", BLUE), "rotate-l": ("⟲", BLUE), "delete": ("🗑", RED), "extract": ("⇱", BLUE),
    "insert": ("⊕", GREEN), "insert-file": ("⊞", GREEN), "reverse": ("⇅", BLUE), "combine": ("⧉", ORANGE),
    "split": ("✂", ORANGE), "crop": ("⌗", BLUE), "flatten": ("▤", GRAY), "header": ("▔", BLUE),
    "watermark": ("W", GRAY), "background": ("▣", YELLOW), "bates": ("№", BLUE),
    "word": ("W", BLUE), "excel": ("X", GREEN), "ppt": ("P", ORANGE), "rtf": ("R", GRAY), "images": ("🖼", GREEN),
    "text": ("Aa", GRAY), "html": ("</>", BLUE), "ocr": ("OCR", ACCENT), "pdfa": ("A", GREEN), "create": ("＋", ACCENT),
    "compare": ("⇋", BLUE), "navigation": ("☰", GRAY), "delete-all": ("🗑", RED), "help": ("?", BLUE),
    "pages": ("▤", GRAY), "bookmarks": ("🔖", GRAY), "comments": ("💬", GRAY), "attachments": ("📎", GRAY),
    "home": ("⌂", ACCENT), "tutorial": ("▶", ACCENT), "merge": ("⧉", BLUE), "move-pages": ("⇅", BLUE),
    "field-text": ("▭", BLUE), "field-check": ("☑", GREEN), "field-radio": ("◉", BLUE), "field-combo": ("▾", BLUE),
    "field-list": ("☰", BLUE), "field-button": ("▢", ORANGE), "field-sign": ("✍", GREEN), "recognize": ("⚡", ACCENT),
    "import": ("⇩", BLUE), "export": ("⇧", BLUE), "reset": ("↺", GRAY), "calc": ("Σ", BLUE), "link": ("🔗", BLUE),
    "layers": ("◫", GRAY), "optimize": ("⇲", GREEN), "audit": ("▥", GRAY), "search-folder": ("🔎", BLUE),
    "first": ("⏮", GRAY), "prev": ("◀", GRAY), "next": ("▶", GRAY), "last": ("⏭", GRAY),
}


def _shape(kind: str, p: QPainter, r: QRectF, color: QColor):
    pen = QPen(color, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    m = r.adjusted(5, 5, -5, -5)
    if kind == "rectangle":
        p.drawRect(m)
    elif kind == "oval":
        p.drawEllipse(m)
    elif kind == "line":
        p.drawLine(m.bottomLeft(), m.topRight())
    elif kind == "arrow":
        a, b = m.bottomLeft(), m.topRight()
        p.drawLine(a, b)
        p.drawLine(b, QPointF(b.x() - 8, b.y()))
        p.drawLine(b, QPointF(b.x(), b.y() + 8))
    elif kind == "polygon":
        p.drawPolygon(QPolygonF([QPointF(m.center().x(), m.top()), QPointF(m.right(), m.center().y() - 2),
                                 QPointF(m.right() - 5, m.bottom()), QPointF(m.left() + 5, m.bottom()),
                                 QPointF(m.left(), m.center().y() - 2)]))
    elif kind == "polyline":
        p.drawPolyline(QPolygonF([m.bottomLeft(), QPointF(m.center().x() - 3, m.top() + 4),
                                  QPointF(m.center().x() + 5, m.bottom() - 2), m.topRight()]))
    elif kind == "cloud":
        path = QPainterPath()
        for i in range(6):
            path.addEllipse(QRectF(m.left() + i * 4, m.top() + (i % 2) * 5, 9, 9))
        p.drawPath(path)
        p.drawRect(QRectF(m.left() + 4, m.top() + 8, m.width() - 8, 6))


SHAPES = {"rectangle", "oval", "line", "arrow", "polygon", "polyline", "cloud"}
_cache: dict[tuple, QIcon] = {}


def _draw(kind: str, size: int) -> QPixmap:
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0, 0, size, size)
    if kind in SHAPES:
        _shape(kind, p, r, QColor(RED))
    else:
        glyph, col = GLYPHS.get(kind, (kind[:1].upper(), GRAY))
        c = QColor(col)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), 38)))
        p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 6, 6)
        f = QFont()
        f.setPixelSize(int(size * (0.34 if len(glyph) > 2 else 0.52 if len(glyph) > 1 else 0.6)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(c.darker(115))
        p.drawText(r, Qt.AlignCenter, glyph)
    p.end()
    return pm


class _LazyIcon(QIconEngine):
    """Draws the icon the first time it is shown. Emoji glyphs are slow to draw (colour-emoji font), and
    most ribbon icons sit on tabs that are never opened, so drawing them all up front slowed start-up."""

    def __init__(self, kind: str, size: int):
        super().__init__()
        self.kind, self.size, self.pm = kind, size, None

    def _pixmap(self) -> QPixmap:
        if self.pm is None:
            self.pm = _draw(self.kind, self.size)
        return self.pm

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self._pixmap())

    def pixmap(self, size, mode, state):
        pm = self._pixmap().scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if mode == QIcon.Disabled:
            return QIcon(pm).pixmap(size, QIcon.Disabled)   # let Qt grey it out
        return pm

    def clone(self):
        return _LazyIcon(self.kind, self.size)


def icon(kind: str, size: int = 32) -> QIcon:
    key = (kind, size)
    if key not in _cache:
        _cache[key] = QIcon(_LazyIcon(kind, size))
    return _cache[key]


# App icon: a page resting on a desk. Teal and amber, kept clear of the red/orange of other PDF tools.
APP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="2" y="2" width="60" height="60" rx="14" fill="#0e5e6f"/>
<path d="M19 11h19l10 10v27a3 3 0 0 1-3 3H19a3 3 0 0 1-3-3V14a3 3 0 0 1 3-3z" fill="#fff"/>
<path d="M38 11v8a2 2 0 0 0 2 2h8z" fill="#9fd3dc"/>
<rect x="22" y="27" width="20" height="3" rx="1.5" fill="#0e5e6f"/>
<rect x="22" y="34" width="14" height="3" rx="1.5" fill="#0e5e6f" opacity=".55"/>
<rect x="9" y="49" width="46" height="6" rx="3" fill="#f2a93b"/>
</svg>
"""


def app_icon() -> QIcon:
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer
    svg = QSvgRenderer(QByteArray(APP_SVG.encode()))
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        svg.render(p)
        p.end()
        ic.addPixmap(pm)
    return ic
