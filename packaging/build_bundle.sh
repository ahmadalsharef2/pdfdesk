#!/usr/bin/env bash
# Freeze pdfdesk into dist/pdfdesk/ with PyInstaller (used by the release workflow on Linux, Windows and macOS,
# where it also makes dist/pdfdesk.app).
# pymupdf imports its AI layout model (onnxruntime) whenever it is installed; pdfdesk never uses it and
# it costs ~0.4 s at every start, so it is left out of the bundle. PaddleX checks its OCR dependencies
# through package metadata, so that metadata is copied in.
set -euo pipefail
mac=()
if [ "$(uname)" = Darwin ]; then      # dist/pdfdesk.app; its icon is drawn from the same SVG as everywhere else
  mkdir -p build/pdfdesk.iconset
  python - <<'PY'
import ast, pymupdf
tree = ast.parse(open("pdfdesk/gui/icons.py").read())
svg = next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "APP_SVG")
page = pymupdf.open(stream=svg.encode(), filetype="svg")[0]
for size in (16, 32, 128, 256, 512):
    for scale, tag in ((1, ""), (2, "@2x")):
        k = size * scale / page.rect.width
        page.get_pixmap(matrix=pymupdf.Matrix(k, k), alpha=True).save(f"build/pdfdesk.iconset/icon_{size}x{size}{tag}.png")
PY
  iconutil -c icns build/pdfdesk.iconset -o build/pdfdesk.icns
  mac=(--icon "$PWD/build/pdfdesk.icns" --osx-bundle-identifier io.github.ahmadalsharef2.pdfdesk)
fi
pyinstaller --noconfirm --windowed --name pdfdesk --paths . --specpath build \
  --collect-submodules pdfdesk --collect-data pdfdesk --collect-all pymupdf --collect-all ocrmypdf --collect-all pyhanko \
  --collect-all paddleocr --collect-all paddlex --collect-all paddle --copy-metadata paddlex --copy-metadata paddleocr \
  --collect-all pyclipper --collect-all shapely --collect-all bidi --hidden-import imagesize \
  $(for d in imagesize opencv-contrib-python pyclipper pypdfium2 python-bidi shapely; do echo --copy-metadata $d; done) \
  --copy-metadata ocrmypdf --copy-metadata pikepdf \
  --exclude-module pymupdf.layout --exclude-module pymupdf4llm --exclude-module onnxruntime \
  ${mac[@]+"${mac[@]}"} packaging/entry.py
