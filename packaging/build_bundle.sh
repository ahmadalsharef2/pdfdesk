#!/usr/bin/env bash
# Freeze pdfdesk into dist/pdfdesk/ with PyInstaller (used by the release workflow on Linux and Windows).
# pymupdf imports its AI layout model (onnxruntime) whenever it is installed; pdfdesk never uses it and
# it costs ~0.4 s at every start, so it is left out of the bundle. PaddleX checks its OCR dependencies
# through package metadata, so that metadata is copied in.
set -euo pipefail
pyinstaller --noconfirm --windowed --name pdfdesk --paths . --specpath build \
  --collect-submodules pdfdesk --collect-all pymupdf --collect-all ocrmypdf --collect-all pyhanko \
  --collect-all paddleocr --collect-all paddlex --collect-all paddle --copy-metadata paddlex --copy-metadata paddleocr \
  --collect-all pyclipper --collect-all shapely --collect-all bidi --hidden-import imagesize \
  $(for d in imagesize opencv-contrib-python pyclipper pypdfium2 python-bidi shapely; do echo --copy-metadata $d; done) \
  --copy-metadata ocrmypdf --copy-metadata pikepdf \
  --exclude-module pymupdf.layout --exclude-module pymupdf4llm --exclude-module onnxruntime \
  packaging/entry.py
