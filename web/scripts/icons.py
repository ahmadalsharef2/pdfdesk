"""Writes the app icon in every size the browser and the phone projects want, from the desktop app's icon
(APP_SVG in pdfdesk/gui/icons.py). Run with the project's Python after the icon changes; the results are kept
in the repository.   ../.venv/bin/python scripts/icons.py"""
import ast
import json
import pathlib

import pymupdf

WEB = pathlib.Path(__file__).resolve().parents[1]
tree = ast.parse((WEB.parent / "pdfdesk" / "gui" / "icons.py").read_text())
SVG = next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "APP_SVG")
ART = SVG.split("\n", 2)[2].rsplit("</svg>", 1)[0]            # everything but the rounded red square
SQUARE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="#b3261e"/>{}</svg>'
# phones cut their own shape out of the icon, so the page sits smaller on a full red square
FULL = SQUARE.format(f'<g transform="translate(9.6 9.6) scale(0.7)">{ART}</g>')
FOREGROUND = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g transform="translate(14.4 14.4) scale(0.55)">{ART}</g></svg>'


def png(svg: str, size: int, path: pathlib.Path, alpha: bool = True):
    page = pymupdf.open(stream=svg.encode(), filetype="svg")[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(matrix=pymupdf.Matrix(size / 64, size / 64), alpha=alpha).save(path)


public = WEB / "public"
(public / "icon.svg").write_text(SVG)
png(SVG, 192, public / "icon-192.png")
png(SVG, 512, public / "icon-512.png")
png(FULL, 512, public / "icon-maskable-512.png", alpha=False)

res = WEB / "android" / "app" / "src" / "main" / "res"
for name, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
    png(SVG, px, res / f"mipmap-{name}" / "ic_launcher.png")
    png(SVG, px, res / f"mipmap-{name}" / "ic_launcher_round.png")
    png(FOREGROUND, px * 9 // 4, res / f"mipmap-{name}" / "ic_launcher_foreground.png")

icons = WEB / "ios" / "App" / "App" / "Assets.xcassets" / "AppIcon.appiconset"
png(FULL, 1024, icons / "AppIcon-512@2x.png", alpha=False)
(icons / "Contents.json").write_text(json.dumps({"images": [{"filename": "AppIcon-512@2x.png", "idiom": "universal", "platform": "ios",
                                                              "size": "1024x1024"}], "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")

# launch screens: the icon on the window's grey, in whatever sizes the projects were made with
INNER = SVG.split("\n", 1)[1].rsplit("</svg>", 1)[0]
for old in [*res.glob("drawable*/splash.png"), *(WEB / "ios" / "App" / "App" / "Assets.xcassets" / "Splash.imageset").glob("*.png")]:
    pix = pymupdf.Pixmap(str(old))
    w, h = pix.width, pix.height
    k = min(w, h) * 0.22 / 64
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" fill="#f3f3f3"/>'
           f'<g transform="translate({w / 2 - 32 * k} {h / 2 - 32 * k}) scale({k})">{INNER}</g></svg>')
    page = pymupdf.open(stream=svg.encode(), filetype="svg")[0]
    page.get_pixmap(matrix=pymupdf.Matrix(w / page.rect.width, h / page.rect.height), alpha=False).save(old)
print("icons written")
