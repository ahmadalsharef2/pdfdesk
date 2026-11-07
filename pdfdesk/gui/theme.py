"""Colours of the window: one accent, everything else derived from it."""
from __future__ import annotations

ACCENT = "#b3261e"          # the File tab, the Start sidebar, checked buttons


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def mix(color: str, with_color: str, amount: float) -> str:
    """`amount` of `color` blended into `with_color` (0 = with_color, 1 = color)."""
    a, b = _rgb(color), _rgb(with_color)
    return "#%02x%02x%02x" % tuple(round(x * amount + y * (1 - amount)) for x, y in zip(a, b))


ACCENT_HOVER = mix(ACCENT, "#ffffff", 0.85)
TINT_HOVER = mix(ACCENT, "#ffffff", 0.10)     # button hover background
TINT_CHECKED = mix(ACCENT, "#ffffff", 0.24)   # checked tool button
TINT_BORDER = mix(ACCENT, "#ffffff", 0.45)    # hover border
BAR = "#f3f3f3"                               # ribbon row, quick access bar, bottom bar
LINE = "#d5d5d5"
TEXT_MUTED = "#777"

RIBBON_STYLE = f"""
QTabBar::tab {{ padding: 6px 12px; border: none; background: transparent; color: #333; }}
QTabBar::tab:selected {{ background: #fff; border-top: 2px solid {ACCENT}; color: #000; }}
QTabBar::tab:hover:!selected {{ background: {TINT_HOVER}; }}
QTabBar::tab:first {{ background: {ACCENT}; color: #fff; padding: 6px 20px; font-weight: bold; }}
QTabBar::tab:first:hover {{ background: {ACCENT_HOVER}; }}
#ribbonBody {{ background: #fff; border-top: 1px solid {LINE}; border-bottom: 1px solid {LINE}; }}
#ribbonRow {{ background: {BAR}; }}
QToolButton {{ border: 1px solid transparent; border-radius: 3px; padding: 2px; background: transparent; color: #222; }}
QToolButton:hover {{ background: {TINT_HOVER}; border-color: {TINT_BORDER}; }}
QToolButton:checked {{ background: {TINT_CHECKED}; border-color: {ACCENT}; }}
QToolButton::menu-indicator {{ image: none; }}
#ribbonBody QScrollArea, #ribbonBody QScrollArea > QWidget > QWidget {{ background: #fff; }}
#ribbonBody QScrollBar:horizontal {{ height: 6px; background: transparent; }}
#ribbonBody QScrollBar::handle:horizontal {{ background: {TINT_BORDER}; border-radius: 3px; min-width: 40px; }}
#ribbonBody QScrollBar::add-line, #ribbonBody QScrollBar::sub-line {{ width: 0; }}
"""
