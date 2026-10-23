"""Icons drawn in code (no image files): simple, flat, one accent colour per command family."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

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
    "edit-text": ("T", BLUE), "add-text": ("T+", BLUE), "image": ("🖼", GREEN), "replace": ("⇄", BLUE),
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


def icon(kind: str, size: int = 32) -> QIcon:
    key = (kind, size)
    if key in _cache:
        return _cache[key]
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
    ic = QIcon(pm)
    _cache[key] = ic
    return ic
