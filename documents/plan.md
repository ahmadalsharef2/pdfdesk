# pdfdesk — build plan

Status: draft for review. Nothing is built until this plan is reviewed.

## Decision recorded

All features of Foxit PhantomPDF Business 10 are in scope, including the ones the manual marks
"Business Edition Only". pdfdesk has no editions, so every feature is an ordinary feature: nothing is
unlocked, because nothing is locked. Each one is written from scratch on open-source libraries.

The agreed limits still hold. Foxit's licence and activation files are not read or changed. No Foxit
code, stamps, cover sheets or other assets are shipped in pdfdesk. Where pdfdesk reads Foxit's file formats
(action sequences, redaction code sets, creation presets, stamps), it does so to import the user's own files.

A few Foxit features have no meaning on Linux or depend on Foxit's own servers. They are listed under
[Not built](#not-built) with the reason for each, so nothing is dropped silently.

## Where the behaviour comes from

The installed `Manual/en-US/Foxit PhantomPDF_Quick Guide.pdf` is the full 446-page user manual, not a
quick guide. It describes every feature and marks the Business-only ones. Each feature section cites its
page. Sources are used in this order, and a later source is used only for a question the earlier ones leave
open:

1. The manual.
2. Foxit's own data files in the install folder. Read so far:
   - `Sequences/<lang>/*.sequ`: Action Wizard actions. They use Adobe Acrobat's workflow format
     (namespace `http://ns.adobe.com/acrobat/workflow/2012`), so pdfdesk can run Foxit and Acrobat
     actions alike. See [08-automation.md](features/08-automation.md).
   - `Redaction/*.xml`: redaction code sets (`<RedactionSet Name>` holding `<RedactionCode Name>`).
   - `Setting/*.xml`: PDF creation presets (`<FXCreatorData>` plus a detached `<Sign>` element).
   - `CompareTamplateFile/*.pdf`: the pieces Foxit uses to build a comparison result.
3. Black-box runs: do the same operation in Foxit under Wine and in pdfdesk on the same input, then
   compare the output PDFs object by object with pikepdf. This answers most "how exactly" questions
   (how a header is marked so it can be removed later, what a redaction annotation holds, what the
   compare result looks like). It works only for features the installed licence covers.
4. REA string and resource searches on Foxit binaries: command names, search-pattern definitions, menu
   and ribbon labels. Each search answers one named question listed under "Open" in a feature section.
5. Ghidra decompilation, only for a named question that 1–4 could not answer.

## Architecture

```
pdfdesk/
  pdfdesk/
    core/        Document wrapper, undo/redo, worker threads, settings
    commands/    one module per feature; each command has a name, typed parameters and run()
    formats/     readers/writers: .sequ, redaction code sets and profiles, creation presets,
                 stamps, FDF/XFDF, comment summaries
    gui/         PySide6 window: ribbon tabs, document tabs, viewer, side panels, dialogs
    cli.py       pdfdesk <command> in.pdf [--param value ...] -o out.pdf, plus Foxit's command lines
  tests/
    corpus/      test PDFs (built by script; Foxit-derived files are local only, git-ignored)
    features/    one test file per feature, holding that feature's before/after example
  documents/     this plan and the feature files
```

- **One command layer for everything.** The GUI, the CLI, batch dialogs and the Action Wizard all call
  the same commands. A command registered under the names used in `.sequ` files (for example
  `RemoveHiddenInfo`, `COMP:AddWatermark`) can run as an Action Wizard step without extra work.
- **Undo/redo** uses PyMuPDF's journal, which works in the installed 1.28.2 (tested: add note, undo, redo).
  Steps done in pikepdf or an external tool (Ghostscript, OCRmyPDF) count as one undo step: pdfdesk keeps
  the previous bytes and swaps the document back.
- **Long jobs** (OCR, compare, batch, index) run on worker threads with progress and Cancel.
- **The ribbon** has Foxit's tabs (checked against the running Foxit): File, Home, Convert, Edit,
  Fill & Sign, Organize, Comment, View, Form, Protect, Share, Connect, Accessibility, Help. Qt has no ribbon widget, so it is built from a tab bar with tool-button groups.
- **Keyboard shortcuts** follow the manual's lists (pp. 436–444), so the same keys do the same things.

## Libraries

| Job | Library | Installed now |
|---|---|---|
| Render, text, annotations, redaction, forms, hidden-data removal, images | PyMuPDF 1.28.2 | yes |
| Low-level objects, encryption, content streams, structure tree | pikepdf | no |
| GUI | PySide6 (Qt 6) | no |
| Signatures, certify, timestamps, certificate encryption | pyHanko | no |
| OCR | Tesseract 5 (eng, ara, deu installed), OCRmyPDF | Tesseract yes, OCRmyPDF no |
| PDF/A and PDF/X conversion, some optimization | Ghostscript | yes |
| PDF/A and PDF/UA validation | veraPDF (Java 21 installed) | no |
| Office to PDF | LibreOffice headless | yes |
| PDF to Word / Excel / PowerPoint | pdf2docx, pdfplumber + openpyxl, python-pptx | openpyxl only |
| Web page to PDF | Playwright with Chromium | no |
| Full-text index | SQLite FTS5 (Python standard library) | yes |
| Read aloud | speech-dispatcher (espeak-ng module), Piper voices | speech-dispatcher yes; Piper's module is missing |
| Spelling | Hunspell dictionaries (ar, de installed; no English) | partly |
| Print | CUPS (`lp`) | yes |
| Virtual printer | cups-pdf | no |
| Scanning | SANE (`scanimage`) | yes |
| Mono image compression | jbig2enc, pngquant, unpaper (OCRmyPDF helpers) | no |
| Cloud drives | rclone | no |
| Barcodes in form fields | segno (QR), pdf417gen | no |

The handoff named diff-pdf for Compare. It only compares rasters and cannot tell an insertion from a
replacement or a formatting change, which Foxit's result report needs. Compare is written on PyMuPDF
text and image extraction instead (see [05-compare.md](features/05-compare.md)).

**Licences.** PyMuPDF and Ghostscript are AGPL-3.0. That is fine for personal use. If pdfdesk is ever
distributed, it must be released under the AGPL or use Artifex's commercial licence.

## Test corpus

Every feature section's example uses one of these files. The script `tests/corpus/build.py` makes
them. Files taken from the Foxit install stay local and are git-ignored.

| Id | File | What it is |
|---|---|---|
| C1 | `manual.pdf` | Foxit's English manual: 446 A4 pages, untagged, 6.4 MB, no forms |
| C2 | `scan.pdf` | Manual pp. 323–325 rasterised at 200 dpi grey, no text layer; page 1 skewed 1.5°, page 2 turned 90° |
| C3 | `contract-v1.pdf`, `contract-v2.pdf` | 6-page document made with LibreOffice. v2 has five known edits: one word replaced on p. 2, a paragraph inserted on p. 3, a table cell changed on p. 4, p. 5 deleted, the image on p. 6 replaced |
| C4 | `form.pdf` | Generated AcroForm with every field type and a calculation (`total = a + b`) |
| C5 | `xfa.pdf` | A public XFA form, to be chosen |
| C6 | `office/` | `letter.docx`, `budget.xlsx`, `slides.pptx`, `drawing.vsdx`, generated with LibreOffice |
| C7 | `arabic.pdf` | One page of mixed Arabic and English text, for right-to-left handling |
| C8 | Foxit fixtures | `Sequences/en-US/*.sequ`, `Redaction/*.xml`, `Setting/*.xml`, `CompareTamplateFile/*.pdf` |

Where Foxit can do the same operation, its output is saved beside pdfdesk's as `foxit-<feature>.pdf`.

## Build order

Phase 0 comes first because every feature needs it. The order after it follows the handoff's
recommendation (organize, OCR, redaction, compare, PDF/A, then sign, Action Wizard, forms), with the rest
appended. Each phase ends with its tests passing and a short review.

| Phase | File | Features |
|---|---|---|
| 0 | [01-foundation.md](features/01-foundation.md) | Window, viewer, select and find, save, undo, print, command line |
| 1 | [02-organize.md](features/02-organize.md) | Pages, combine, split, crop, flatten, header/footer, watermark, background, Bates, page labels |
| 2 | [03-ocr-scan.md](features/03-ocr-scan.md) | OCR, OCR suspects, scan, optimize scanned, PDF Optimizer |
| 3 | [04-protect.md](features/04-protect.md) | Redaction (all of it), whiteout, remove hidden data, password and certificate security, trust |
| 4 | [05-compare.md](features/05-compare.md) | Compare |
| 5 | [06-standards.md](features/06-standards.md) | Preflight, PDF/A, PDF/E, PDF/X, PDF/UA |
| 6 | [07-sign.md](features/07-sign.md) | Digital IDs, sign, certify, timestamp, validate, PAdES, Fill & Sign |
| 7 | [08-automation.md](features/08-automation.md) | Action Wizard, shared batch dialog |
| 8 | [09-forms.md](features/09-forms.md) | Fill, XFA, create fields, field recognition, form data, JavaScript |
| 9 | [10-comment.md](features/10-comment.md) | All comment tools, measure, stamps, manage, summarize, import/export |
| 10 | [11-create-export.md](features/11-create-export.md) | Create from files, web, printer, presets, portfolio, export to Office and images |
| 11 | [12-edit.md](features/12-edit.md) | Text and object editing, image editor, links, bookmarks, layers, multimedia, properties |
| 12 | [13-search-access-read.md](features/13-search-access-read.md) | Advanced search, index, accessibility check and tagging, read aloud |
| 13 | [14-share.md](features/14-share.md) | Email, shared review, cloud drives, DocuSign, DMS connectors, sensitivity labels |

Comments (phase 9) are used every day. Moving them to just after phase 0 costs nothing, because
redaction marks already need the annotation layer.

## Known weak spots

These will work, but not as well as Foxit:

- **Editing existing text with paragraph reflow.** No open-source library edits PDF text in place.
  pdfdesk removes the old glyphs and sets new text in the same font when its glyphs are embedded, or the
  closest installed font when they are not.
- **Export to Word, Excel and PowerPoint.** pdf2docx is good on simple layouts and weak on complex ones.
  Excel export depends on table detection.
- **XFA forms.** Only PDFium built with XFA support can fill dynamic XFA forms. This is the biggest
  technical risk and is tested first in phase 8.
- **Automatic tagging for accessibility.** pdfdesk builds tags from layout analysis (headings from font
  size, tables from table detection, reading order from block order). Expect to fix tags by hand more
  often than in Foxit.
- **PDF/E and PDF/X checks.** No free validator exists. pdfdesk converts with Ghostscript and runs its
  own checks for the main rules.
- **Foxit's "High Compression"** for scans uses mixed raster content. pdfdesk uses JBIG2 and JPEG through
  OCRmyPDF's optimizer, which comes close on text scans and less close on mixed pages.

## Not built

| Foxit feature | Reason |
|---|---|
| ConnectedPDF (tracking, versions, clone, enforced tracking, online protection) | Runs on Foxit's servers |
| Foxit DRM / RMS server protection, Foxit account, Foxit Drive, Subscribe | Foxit's servers |
| Foxit Admin Console, Update Server, GPO, Setup Customization Tool | Windows fleet deployment; pdfdesk is one user's app |
| Windows Information Protection (WIP) | Windows only, and retired by Microsoft |
| FIPS mode | Windows crypto policy; on Linux this is set system-wide by the OS |
| VBA / COM automation from Excel | Windows only; pdfdesk's CLI and Python commands do the same job |
| Foxit plug-in platform (`.fpi`) | Foxit plug-ins are Windows binaries built against Foxit's SDK; pdfdesk has its own command modules |
| Create from Microsoft Project (`.mpp`) | No open-source reader for `.mpp` |
| 3D content (U3D, PRC) | No usable open-source 3D PDF viewer |
| Internet Explorer add-in | No IE on Linux |

Two depend on accounts and are built only if the user has one to test against. Both are in
[14-share.md](features/14-share.md):

- AIP sensitivity labels and "redacted + AIP-protected PDF" need a Microsoft 365 tenant with
  Information Protection. Microsoft's MIP SDK has Linux builds.
- DocuSign and each document-management connector need an account on that service.

## Dependencies to install

Nothing is installed until the plan is approved. All Python packages go in a project venv (`.venv`).

- pip: `pymupdf PySide6 pikepdf ocrmypdf "pyhanko[pkcs11,image-support,opentype]" pdf2docx pdfplumber
  openpyxl python-docx python-pptx segno pdf417gen img2pdf pillow playwright spylls pytest`
- apt (needs sudo, so the user runs it): `printer-driver-cups-pdf unpaper pngquant hunspell-en-us rclone`
  plus `tesseract-ocr-<lang>` for any further OCR languages.
- jbig2enc: from apt if this release packages it, otherwise built from source.
- veraPDF: the Java installer from verapdf.org.
- Playwright: `playwright install chromium`, which downloads Chromium into `~/.cache`.

## Questions for review

1. ~~Which edition?~~ Answered: Help > About shows **Business 10.0.0.35798**. Foxit can produce reference
   output for Business-only features in Wine. pdfdesk still never reads the licence files.
2. **Which accounts exist?** Microsoft 365 with AIP labels, DocuSign, Google Drive, OneDrive, Dropbox,
   Box, SharePoint, any document-management system. Connectors with no account to test against are
   left until one exists.
3. **Stack:** Python 3.12, PySide6 and PyMuPDF, with the AGPL note above. Agreed?
4. **Order:** keep the order above, or move comments to phase 1?
5. **Languages:** OCR has Arabic, English and German. Spelling has Arabic and German but no English.
   Which others?
