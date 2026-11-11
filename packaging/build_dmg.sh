#!/usr/bin/env bash
# Build dist/pdfdesk-<version>-macos-arm64.dmg from dist/pdfdesk.app (run packaging/build_bundle.sh first, on a Mac).
# The app is signed "ad hoc" only: without an Apple Developer ID macOS asks before the first start
# (right-click > Open, or System Settings > Privacy & Security > Open Anyway). To sign for real, replace "-"
# below with the Developer ID and notarize the .dmg.
set -euo pipefail
version="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)}"
app=dist/pdfdesk.app
plist="$app/Contents/Info.plist"
buddy() { /usr/libexec/PlistBuddy -c "$1" "$plist"; }
buddy "Set :CFBundleShortVersionString $version"
buddy "Add :CFBundleVersion string $version" 2>/dev/null || buddy "Set :CFBundleVersion $version"
# Finder offers pdfdesk under "Open With" for PDF files; the app gets them as file-open events (gui/app.py)
buddy "Add :CFBundleDocumentTypes array"
buddy "Add :CFBundleDocumentTypes:0 dict"
buddy "Add :CFBundleDocumentTypes:0:CFBundleTypeName string PDF"
buddy "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Editor"
buddy "Add :CFBundleDocumentTypes:0:LSHandlerRank string Alternate"
buddy "Add :CFBundleDocumentTypes:0:LSItemContentTypes array"
buddy "Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string com.adobe.pdf"
codesign --force --deep --sign - "$app"       # the changed Info.plist needs a fresh signature
stage=build/dmg
rm -rf "$stage"
mkdir -p "$stage"
cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
hdiutil create -volname pdfdesk -srcfolder "$stage" -ov -format UDZO "dist/pdfdesk-$version-macos-arm64.dmg"
