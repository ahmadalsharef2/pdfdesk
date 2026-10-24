#!/usr/bin/env bash
# Build dist/pdfdesk_<version>_amd64.deb from the PyInstaller folder in dist/pdfdesk.
# Usage: packaging/build_deb.sh <version>
set -euo pipefail
umask 022
version="${1:?version}"
root="build/deb"
rm -rf "$root"
mkdir -p "$root/DEBIAN" "$root/opt" "$root/usr/bin" "$root/usr/share/applications"
cp -r dist/pdfdesk "$root/opt/pdfdesk"
ln -s /opt/pdfdesk/pdfdesk "$root/usr/bin/pdfdesk"
cp packaging/pdfdesk.desktop "$root/usr/share/applications/"
cat > "$root/DEBIAN/control" <<CTRL
Package: pdfdesk
Version: $version
Section: utils
Priority: optional
Architecture: amd64
Maintainer: ahmadalsharef994 <ahmadalsharef994@users.noreply.github.com>
Depends: libxcb-cursor0, fontconfig
Recommends: ghostscript, tesseract-ocr, tesseract-ocr-eng, tesseract-ocr-osd, libreoffice-writer, libreoffice-calc, libreoffice-impress, libreoffice-draw, fonts-dejavu-core, fonts-liberation, fonts-noto-core, cups-client, xdg-utils
Description: PDF editor modelled on Foxit PhantomPDF
CTRL
dpkg-deb --build --root-owner-group "$root" "dist/pdfdesk_${version}_amd64.deb"
