# pdfdesk — session handoff

## Goal and intention

Ahmad wants a Linux PDF editor for personal use that does what **Foxit PhantomPDF Business 10** does,
**including the Business-only features**, built on open-source libraries. Foxit's own install (Wine) and the
REA tools are used only to study how features behave (formats, sequences, output) so pdfdesk behaves the
same. Foxit's code, stamps and assets are not copied.

How to work with Ahmad: they want **a working app, not documents**. They were frustrated when this session
produced plans before code, and again by tests. Build features, show that they run, keep reports short, and
do not write more planning documents or test files unless asked.

## Limits agreed

- Foxit's activation and licence files are not touched: `Activation.exe`, `LicenseManager.fpi`.
- Foxit's code is not carried into pdfdesk. REA findings describe behaviour and formats only.
- Foxit's online services (Connected PDF, DRM, Foxit account, Foxit Drive) are not reproduced.
  Cloud and document-management connectors are built one at a time against each service's own API, and only
  when there is an account to test against.

## How to run

```
cd /home/ahmad/projects/pdfdesk && .venv/bin/python -m pdfdesk.cli [file.pdf]
```

The Qt window needs `sudo apt install libxcb-cursor0` (not installed at the time of writing, the first launch
failed on it). On Wayland, `QT_QPA_PLATFORM=wayland` is an alternative. Command line, no window:
`.venv/bin/python -m pdfdesk.cli run <Command> in.pdf -o out.pdf --key value`, and
`.venv/bin/python -m pdfdesk.cli commands` lists every command.

Environment: `.venv` in the project (Python 3.12) holds PyMuPDF 2.0 (MuPDF 1.28.5), pikepdf, PySide6 6.12,
OCRmyPDF, pyHanko 0.38, pdf2docx, pdfplumber, openpyxl, python-docx, python-pptx, img2pdf. System tools used:
Tesseract (eng, ara, deu), Ghostscript, LibreOffice. Not installed: qpdf, unpaper, jbig2enc, pngquant, veraPDF,
Docker, hunspell-en, cups-pdf.

## What is built

Code is in `pdfdesk/`. Every feature is a named command in `pdfdesk/commands/` (the GUI, CLI and, later,
Action Wizard all call the same commands).

### Verified by running it (commands, checked on real output)

- **Organize** (`organize.py`): rotate, delete, reverse, move, insert blank/file, extract, replace, combine
  with bookmarks, split by count or bookmarks, crop, flatten, page labels, header/footer with page and Bates
  macros, watermark, background. Remove-watermark was checked; remove-header/footer and remove-background
  were not.
- **Redaction** (`protect.py`): mark by rectangle, page, text, regex or named pattern (email, phones, card with
  Luhn, SSN, SIN, IBAN, date); apply; whiteout. Checked that redacted text is gone from the text layer and
  from the raw bytes of the saved file.
- **Other protect**: remove hidden info, AES-256 encrypt.
- **Security-preserving save** (`core/security.py`): PyMuPDF 2.0 drops encryption on any full save, so pdfdesk
  keeps the passwords and permissions with the document and re-applies them on save, and refuses to write an
  unprotected copy silently. Checked.
- **OCR** (`ocr.py`): two outputs. *Searchable* (`Ocr.Run`): OCRmyPDF + Tesseract, invisible text under the
  image. *Editable* (`Ocr.Editable`, Ahmad's preferred one, like Foxit's "Editable Text"): Tesseract finds
  lines and confidences, each line is painted out with the sampled background colour and set back as real
  visible text (size normalised per paragraph, bold guessed from ink density, text scaled to the line width);
  pictures stay as the background. Checked on two rasterised manual pages: 97.4% word recall against the real
  text, and `Text.EditLine` / `Text.Replace` work on the result. Limits: one sans font for everything,
  occasional wrong bold, no deskew/rotation handling, no OCR-suspects panel yet (the list of low-confidence
  words is returned but not shown). Foxit's engine is ABBYY; Tesseract is the open-source stand-in and was not
  benchmarked against it.
- **Compare** (`compare.py`): word-stream diff over the whole document; found exactly the planted replacement
  and insertion on the contract v1/v2 pair; result PDF has a summary page and side-by-side pages with
  annotations. Not done: formatting, table, whole-page and image-replacement changes (image code untested).
- **Edit text** (`edit.py`): replace a line keeping font, size, colour and baseline (embedded font if it has the
  glyphs, else the installed match, else base-14); find/replace all; add text, including Arabic (right-to-left
  with a font that extracts correctly). Checked on the contract file and on Foxit's manual heading.
- **Comment tools** (`comment.py`): highlight, underline, strikeout, squiggly, replace text, insert text, area
  highlight, note, file attachment, typewriter, text box, callout, rectangle, oval, line, arrow, polygon,
  cloud, polyline, pencil, stamp, list/select/delete/move/edit. All created and read back.
- **Signatures** (`sign.py`): typed/drawn/image signature placed on the page; self-signed digital ID; digital
  sign with a visible field; certify; validate with trust, intact and changes-after-signing reported.
  Checked with pyHanko.
- **Convert** (`convert.py`): create PDF from Office (via LibreOffice), images, text, HTML; combine mixed
  files; export to images (PNG/JPEG/TIFF), text, HTML, Word, RTF, Excel, PowerPoint; PDF/A through
  OCRmyPDF/Ghostscript. PDF/A was checked only by the XMP claim and presence of an output intent, **not
  validated with veraPDF**.
- 25 earlier tests passed (organize, protect, compare, OCR, edit, comment, sign, convert, security). The
  suite is in `tests/`.

### Written but not exercised

- **The GUI** (`pdfdesk/gui/`), laid out like Foxit PhantomPDF 10 (layout, not style; own icons, purple accent):
  `ribbon.py` (File tab, 14 tabs, "Tell me what you want to do…" box, Find box, groups with names underneath,
  large / stacked / icon-grid buttons; Hand and Select at the left of most tabs), `app.py` (quick-access bar,
  document tabs, navigation pane with an icon strip for Pages / Bookmarks / Comments / Attachments toggled by
  F4, bottom bar with page navigation, page box and zoom, undo/redo, save), `start.py` (Start page: sidebar,
  Tool Wizard cards, Recent list), `icons.py` (icons drawn in code), `viewer.py` (continuous scroll, mouse tools,
  inline text editor, snapshot undo), `dialogs.py`, `panels.py`. It was started offscreen and screenshotted
  (Start page, Comment tab and Protect tab look right). Through the code path it opened the 446-page manual,
  ran editable OCR and undid it. **No mouse tool, dialog or menu has been used by hand on a real screen yet.**
  Expect bugs. Not copied from Foxit: icons, stamps, any asset. The Comment tab groups follow Foxit's real tab
  (Tools, Text Markup, Pin, Typewriter, Drawing, Stamp, Manage); other tabs follow the manual and are
  approximate, so send screenshots of a Foxit tab to match it more closely.
- **`tests/test_gui.py` is stale**: it is the first version and will fail against the new window. The
  rewritten GUI tests were never saved (the user declined them). Delete or rewrite when needed.
- Ribbon tabs **Form, Share, Connect, Accessibility** only show a "later phase" label. File, Home, Convert,
  Edit, Fill & Sign, Organize, Comment, View, Protect and Help have buttons.

### Not built

- Forms (fill, create fields, XFA, JavaScript), Action Wizard and the `.sequ` runner, preflight and PDF/A
  checks with veraPDF, layers, links, bookmarks editing, article threads, advanced search and full-text index,
  accessibility check and tagging, read aloud, portfolios, scanner input, virtual printer, PDF Optimizer
  (advanced), page-level image editor, redaction code sets and profiles, shared review, cloud/DMS connectors,
  sensitivity labels. See the plan.
- Known gaps in what exists: editing is per line (no paragraph reflow); header/footer, watermark and
  background removal relies on stream surgery that is only partly checked; text added with a script font
  depends on installed fonts.

## The plan documents

`documents/plan.md` and `documents/features/01-…14-*.md` describe about 100 features: Foxit's behaviour (with
manual page numbers), the library to use, an example and how to check it. Written first, before Ahmad said to
build; use them as a checklist, not as work to extend. Facts established there:

- The installed Foxit is **Business 10.0.0.35798** (Help > About), so Foxit under Wine can produce reference
  output for Business-only features. The ribbon tabs are File, Home, Convert, Edit, Fill & Sign, Organize,
  Comment, View, Form, Protect, Share, Connect, Accessibility, Help.
- `Manual/en-US/Foxit PhantomPDF_Quick Guide.pdf` is the full 446-page manual and marks Business-only items.
- `Sequences/*.sequ` are Adobe Acrobat workflow files (namespace `http://ns.adobe.com/acrobat/workflow/2012`);
  5 ship in English and use 19 commands. `Redaction/*.xml` are code sets. `Setting/*.xml` are creation presets
  with a detached `<Sign>` element (not well-formed XML). Details in `documents/features/`.
- Not reproducible: ConnectedPDF, DRM, Foxit account, Admin Console, GPO, WIP, FIPS, VBA, `.fpi` plug-ins,
  Project (`.mpp`), 3D, the IE add-in.
- Licence: PyMuPDF and Ghostscript are AGPL-3.0. Fine for personal use; distributing pdfdesk would need AGPL.

## Next steps

1. Install `libxcb-cursor0`, launch the window, and fix whatever breaks when the tools are used by hand.
   Ahmad's last questions were whether add text, edit text, merge, delete page, convert and signatures work:
   they are all implemented as commands and wired to buttons, but only the commands are verified.
2. Then in this order (Ahmad's priorities were organize, OCR, redaction, compare, PDF/A, signing,
   Action Wizard, forms): forms, Action Wizard running Foxit's own `.sequ` files, PDF/A validation with
   veraPDF, layers/links/bookmarks, search/index, accessibility, the remaining Share/Connect items.
3. Open questions still to settle with Foxit-under-Wine or REA (listed per feature under "Open" in the plan):
   header/footer and watermark markers, `Scan:OPT` integer codes, creation-preset codes, Foxit's search-pattern
   list, shared-review folder layout.

## Where Foxit is

Wine bundle `~/Apps/FoxitPhantomPDF/` (repair with `~/Apps/FoxitPhantomPDF/install.sh`, never apt Wine).
Program folder: `~/Apps/FoxitPhantomPDF/prefix/drive_c/Program Files (x86)/Foxit Software/Foxit PhantomPDF`.
A copy of the manual is at `tests/corpus/foxit/manual.pdf` (git-ignored, local only).

## REA setup (unchanged from the previous session)

REA 6.7.0 is registered for Claude Code; Ghidra 12.1.4 in `~/Apps/ghidra_12.1.4_PUBLIC`, Java 21, Node 22.20.0
through nvm. Every REA command starts with
`source ~/.nvm/nvm.sh && nvm use 22.20.0 && export GHIDRA_INSTALL_DIR="$HOME/Apps/ghidra_12.1.4_PUBLIC"`.
Health: `npx -y rea-agents@6.7.0 doctor`. Only `inspect-artifact` was run on `FoxitPhantomPDF.exe`; no Ghidra
analysis yet. Do that only for one named question at a time.
Oddities: `~/.npmrc` has `prefix=/home/ahmad/.local` (nvm warns on every shell); Claude Code's auto mode
blocked setup commands earlier, so privileged or system-wide steps are run by Ahmad in their terminal.
