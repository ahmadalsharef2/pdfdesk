#!/usr/bin/env bash
# Build dist/pdfdesk_<version>_amd64.deb from the PyInstaller folder in dist/pdfdesk.
# Usage: packaging/build_deb.sh [version]   (run packaging/build_bundle.sh first; version defaults to pyproject)
set -euo pipefail
umask 022
version="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)}"
root="build/deb"
rm -rf "$root"
mkdir -p "$root/DEBIAN" "$root/opt" "$root/usr/bin" "$root/usr/share/applications"
cp -r dist/pdfdesk "$root/opt/pdfdesk"
ln -s /opt/pdfdesk/pdfdesk "$root/usr/bin/pdfdesk"
cp packaging/linux/pdfdesk.desktop "$root/usr/share/applications/"
# right-click entries in the file managers: Nautilus (GNOME, Zorin), Nemo (Mint), Dolphin (KDE 5 and 6)
install -Dm644 packaging/linux/pdfdesk-nautilus.py "$root/usr/share/nautilus-python/extensions/pdfdesk.py"
install -Dm644 -t "$root/usr/share/nemo/actions" packaging/linux/pdfdesk-combine.nemo_action packaging/linux/pdfdesk-convert.nemo_action
install -Dm755 packaging/linux/pdfdesk-servicemenu.desktop "$root/usr/share/kio/servicemenus/pdfdesk.desktop"
install -Dm644 packaging/linux/pdfdesk-servicemenu.desktop "$root/usr/share/kservices5/ServiceMenus/pdfdesk.desktop"
mkdir -p "$root/usr/share/icons/hicolor/scalable/apps"
# read APP_SVG from the source without importing Qt (CI runners may lack libEGL)
python -c "import ast; t = ast.parse(open('pdfdesk/gui/icons.py').read()); print(next(n.value.value for n in t.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'APP_SVG'), end='')" \
  > "$root/usr/share/icons/hicolor/scalable/apps/pdfdesk.svg"
cat > "$root/DEBIAN/control" <<CTRL
Package: pdfdesk
Version: $version
Section: utils
Priority: optional
Architecture: amd64
Maintainer: ahmadalsharef994 <ahmadalsharef994@users.noreply.github.com>
Depends: libxcb-cursor0, fontconfig
Recommends: python3-nautilus, ghostscript, libreoffice-writer, libreoffice-calc, libreoffice-impress, libreoffice-draw, fonts-dejavu-core, fonts-liberation, fonts-noto-core, cups-client, xdg-utils
Description: PDF editor modelled on Foxit PhantomPDF
CTRL
cat > "$root/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
update-desktop-database -q /usr/share/applications 2>/dev/null || true
POST
chmod 755 "$root/DEBIAN/postinst"
dpkg-deb --build --root-owner-group "$root" "dist/pdfdesk_${version}_amd64.deb"
