# Installing pdfdesk

Tested on Zorin OS 18 (Ubuntu 24.04 base), Python 3.12.

## System packages (apt, need sudo)

Required to start the window and use the main features:

| Package | Used for |
|---|---|
| `libxcb-cursor0` | Qt's X11 plugin. Without it the window aborts at start |
| `ghostscript` | PDF/A conversion (through OCRmyPDF) |
| `tesseract-ocr`, `tesseract-ocr-eng`, `tesseract-ocr-osd` | OCR; `osd` lets it detect page rotation |
| `libreoffice-writer`, `libreoffice-calc`, `libreoffice-impress`, `libreoffice-draw` | Create PDF from Word, Excel, PowerPoint, Visio/Draw files, and export to RTF |
| `fontconfig` | Finding installed fonts (`fc-list`) |
| `fonts-dejavu-core`, `fonts-liberation`, `fonts-noto-core` | Fonts for editing and adding text. Noto Sans Arabic is used for Arabic |
| `python3-venv` | Making the virtual environment |

```
sudo apt install libxcb-cursor0 ghostscript tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd \
  libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw \
  fontconfig fonts-dejavu-core fonts-liberation fonts-noto-core python3-venv
```

More OCR languages: `sudo apt install tesseract-ocr-deu tesseract-ocr-ara` (replace with the language code).

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
