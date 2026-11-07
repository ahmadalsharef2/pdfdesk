# Installing pdfdesk

Tested on Zorin OS 18 (Ubuntu 24.04 base), Python 3.12.

## System packages (apt, need sudo)

Required to start the window and use the main features:

| Package | Used for |
|---|---|
| `libxcb-cursor0` | Qt's X11 plugin. Without it the window aborts at start |
| `ghostscript` | PDF/A conversion (through OCRmyPDF) |
| `libreoffice-writer`, `libreoffice-calc`, `libreoffice-impress`, `libreoffice-draw` | Create PDF from Word, Excel, PowerPoint, Visio/Draw files, and export to RTF |
| `fontconfig` | Finding installed fonts (`fc-list`) |
| `fonts-dejavu-core`, `fonts-liberation`, `fonts-noto-core` | Fonts for editing and adding text. Noto Sans Arabic is used for Arabic |
| `python3-venv` | Making the virtual environment |

```
sudo apt install libxcb-cursor0 ghostscript \
  libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw \
  fontconfig fonts-dejavu-core fonts-liberation fonts-noto-core python3-venv
```

OCR uses PaddleOCR (a Python package, no system package). The first OCR run downloads its models (about 100 MB per
language) to `~/.paddlex`; after that it works offline.
The window language (English, Deutsch, العربية) is chosen under File > Language.

Used when present (the app works without them):

| Package | Used for |
|---|---|
| `cups-client` | Print (`lp`, `lpstat`) |
| `xdg-utils` | Email a document (`xdg-email`) |
| `sane-utils` | Scanning (`scanimage`), not wired to a button yet |
| `unpaper`, `pngquant`, `jbig2enc-tools` | Smaller scanned PDFs through OCRmyPDF's optimizer (`optimize` above 1) |

Needed by planned features, not by anything built yet: `veraPDF` (Java installer from verapdf.org) for PDF/A
and PDF/UA validation, `hunspell-en-us` for spell check, `speech-dispatcher` for read aloud,
`printer-driver-cups-pdf` for a virtual PDF printer, `rclone` for cloud drives.

## Python packages

All in [requirements.txt](requirements.txt), installed into a project virtual environment:

```
cd /home/ahmad/projects/pdfdesk
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If the Qt window fails with "Could not load the Qt platform plugin xcb", `libxcb-cursor0` is missing. On
Wayland you can also start it with `QT_QPA_PLATFORM=wayland`.

## Run

```
.venv/bin/python -m pdfdesk.cli [file.pdf]
```

## Licences to be aware of

PyMuPDF and Ghostscript are AGPL-3.0. That is fine for personal use. Distributing pdfdesk to others would
require releasing it under the AGPL or buying Artifex's commercial licence.

## Right-click menus

The .deb adds "Combine files in pdfdesk" and "Convert to PDF in pdfdesk" to the file manager: Nautilus (GNOME,
Zorin; needs `python3-nautilus`, then `nautilus -q` once to reload), Nemo (Mint) and Dolphin (KDE). The Windows
installer adds the same two entries to Explorer (Windows 11: under "Show more options").
