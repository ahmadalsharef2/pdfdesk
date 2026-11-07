"""Nautilus (GNOME Files) right-click entries for pdfdesk: Combine files, Convert to PDF.
Installed to /usr/share/nautilus-python/extensions/; needs python3-nautilus. Runs inside Nautilus."""
import configparser
import os
import subprocess

from gi.repository import GObject, Nautilus

PDF = {"pdf"}
OTHER = set("bmp cbz csv doc docx dps epub et fb2 gif htm html jp2 jpeg jpg jxr key numbers odg odp ods odt pages png "
            "pnm ppt pptx rtf svg tif tiff txt vsd vsdx webp wpd wps xhtml xls xlsx xps".split())
LABELS = {
    "en": ("Combine files in pdfdesk", "Convert to PDF in pdfdesk"),
    "de": ("Dateien in pdfdesk zusammenführen", "In pdfdesk in PDF konvertieren"),
    "ar": ("دمج الملفات في pdfdesk", "تحويل إلى PDF في pdfdesk"),
}


def _language() -> str:
    """pdfdesk's own choice (File > Language), else the desktop's language."""
    conf = configparser.ConfigParser()
    conf.read(os.path.expanduser("~/.config/pdfdesk/pdfdesk.conf"))
    code = conf.get("General", "language", fallback="") or os.environ.get("LANG", "en")[:2]
    return code if code in LABELS else "en"


def _ext(path: str) -> str:
    return os.path.splitext(path)[1][1:].lower()


class PdfdeskMenu(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, *args):            # (files) in Nautilus 43+, (window, files) before
        files = args[-1]
        paths = [f.get_location().get_path() for f in files if f.get_uri_scheme() == "file" and not f.is_directory()]
        if not paths or len(paths) != len(files) or any(_ext(p) not in PDF | OTHER for p in paths):
            return []
        combine, convert = LABELS[_language()]
        items = []
        if len(paths) >= 2:
            items.append(self._item("combine", combine, paths))
        if any(_ext(p) in OTHER for p in paths):
            items.append(self._item("convert", convert, paths))
        return items

    @staticmethod
    def _item(action: str, label: str, paths: list[str]):
        item = Nautilus.MenuItem(name=f"pdfdesk::{action}", label=label, icon="pdfdesk")
        item.connect("activate", lambda *_: subprocess.Popen(["pdfdesk", f"--{action}", *paths], start_new_session=True))
        return item
