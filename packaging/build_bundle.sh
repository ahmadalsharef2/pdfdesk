#!/usr/bin/env bash
# Freeze pdfdesk into dist/pdfdesk/ with PyInstaller (used by the release workflow on Linux and Windows).
set -euo pipefail
pyinstaller --noconfirm --windowed --name pdfdesk --paths . --specpath build \
  --collect-submodules pdfdesk --collect-all pymupdf --collect-all ocrmypdf --collect-all pyhanko \
  --copy-metadata ocrmypdf --copy-metadata pikepdf \
  packaging/entry.py
