"""User-interface languages. `tr("English text")` returns the text in the chosen language; the English
string is the key, so untranslated strings fall back to English."""
from __future__ import annotations

from . import ar, de

LANGUAGES = {"en": "English", "de": "Deutsch", "ar": "العربية"}
RTL = {"ar"}
_code = "en"
_table: dict[str, str] = {}


def tr(text: str, **values) -> str:
    s = _table.get(text, text)
    return s.format(**values) if values else s


def set_language(code: str):
    global _code, _table
    _code = code if code in LANGUAGES else "en"
    _table = {"de": de.STRINGS, "ar": ar.STRINGS}.get(_code, {})


def language() -> str:
    return _code


def ocr_languages() -> str:
    """Default OCR languages for the interface language (PaddleOCR codes)."""
    return {"de": "de", "ar": "ar+en"}.get(_code, "en")


def is_rtl() -> bool:
    return _code in RTL


def install(app, code: str):
    """Apply the language to a QApplication: layout direction and Qt's own dialog strings."""
    from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
    set_language(code)
    app.setLayoutDirection(Qt.RightToLeft if is_rtl() else Qt.LeftToRight)
    old = getattr(app, "_pdfdesk_translator", None)
    if old is not None:
        app.removeTranslator(old)
        app._pdfdesk_translator = None
    if _code != "en":
        t = QTranslator(app)
        if t.load(QLocale(_code), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(t)
            app._pdfdesk_translator = t       # keep it alive
