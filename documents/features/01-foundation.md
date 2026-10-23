# Phase 0 — Foundation

Every later feature runs inside this. Page numbers refer to the Foxit manual (corpus file C1).

### F01 Window and ribbon

- **Foxit** (pp. 16–23): ribbon with File, Home, Convert, Edit, Organize, Comment, View, Form, Protect,
  Share, Accessibility and Help tabs. Tabbed documents. Quick Access Toolbar that the user can edit.
  Customizable ribbon. Skins. Mouse and touch modes.
- **pdfdesk:** PySide6 main window. The ribbon is a tab bar over tool-button groups, built from a
  declarative table (tab → group → command name), so the toolbar editor can rewrite it. Light and dark
  themes stand in for skins. Touch mode makes buttons larger.
- **Example:** before: no window. After: `pdfdesk C1` opens the manual in a tab with all fourteen ribbon
  tabs. **Check:** GUI test lists the tab labels and opens the Quick Access editor.
- **Open:** the exact group and button layout of each tab. Source: REA `inspect-pe-resources` on
  `FoxitPhantomPDF.exe`, or screenshots of Foxit under Wine.

### F02 Viewer

- **Foxit** (pp. 57–72): single page, continuous, facing, continuous facing, separate cover page;
  zoom to actual size, fit page, fit width, fit visible, marquee and loupe zoom; rotate view; read mode,
  full screen, reverse view, split view; night mode. Panels for thumbnails, bookmarks, layers,
  attachments, comments, signatures and destinations. Logical page numbers (page labels) in navigation.
- **pdfdesk:** pages rendered by PyMuPDF to `QImage` tiles on a worker thread with an LRU cache.
  Only visible tiles render. Panels are dock widgets.
- **Example:** before: C1 closed. After: C1 opens at p. 1 in under a second, scrolls smoothly to the end,
  and "Go to page vii" jumps by label when labels exist. **Check:** a raster of p. 323 at 100 % matches
  `pdftoppm -r 72` within a small per-pixel tolerance. Open time is measured in a test.

### F03 Select, copy, find, word count

- **Foxit** (pp. 73–76, 86): select text, images, and areas (snapshot); copy with or without formatting;
  Find bar with match case and whole word; highlight all results (v10); word count for the whole document
  or a selection (words, characters with and without spaces, pages, lines).
- **pdfdesk:** PyMuPDF word boxes for selection and copy. Right-to-left runs are copied in logical
  order. Find uses the same text page.
- **Example:** before: C1 p. 323. After: dragging over the heading "Mark for Redaction" copies exactly
  that string. Find "redaction" highlights every hit on pp. 323–328. On C7, copying an Arabic line gives the
  same characters in the same order as the source document. **Check:** clipboard text compared with the
  expected strings.
- **Open:** Foxit's word-count rules (hyphenated words, numbers, Arabic). Black-box: count C1 p. 323 and
  C7 in Foxit.

### F04 Open, save, undo, properties

- **Foxit** (pp. 49–52, 119, 189): open from disk or recent files; password prompt; save, save as,
  incremental save; undo/redo across edits; document properties (description, initial view, security,
  fonts, advanced, custom).
- **pdfdesk:** PyMuPDF journal for undo/redo (tested on 1.28.2). Saves are incremental unless the
  document must be rewritten. Properties dialog over PyMuPDF metadata, XMP and the catalog's view
  preferences.
- **Example:** before: C1 with no notes. After: add a note on p. 1, undo, redo, save incrementally.
  **Check:** pikepdf shows a trailer with `/Prev`, and one Text annotation on p. 1.

### F05 Print

- **Foxit** (pp. 381–390): printer, copies, page range (including odd/even and current view), scaling
  (none, fit, shrink, custom), multiple pages per sheet, booklet, tile large pages, print as image,
  grayscale, print comments and form fields, collate, duplex.
- **pdfdesk:** Qt print dialog for printer selection, CUPS (`lp`) for the job. N-up, booklet and tiling
  are composed into a temporary PDF with PyMuPDF `show_pdf_page`, so CUPS receives finished sheets.
- **Example:** before: C1 pp. 1–8. After: booklet printing makes a 2-sheet PDF whose page order is
  8,1 / 2,7 / 6,3 / 4,5. **Check:** the temporary print PDF has 4 sides in that order.

### F06 Command line

- **Foxit** (p. 445): `-pwd<password>`, `/p <file>` (print to default printer), `/t <file> [printer]`,
  `<file> /A page=… zoom=…`, `/A reverse=1|0`, `-Register` (default reader).
- **pdfdesk:** the same switches, plus `pdfdesk run <command> <files> [--param …]` for every command,
  and a `.desktop` file that registers pdfdesk for `application/pdf` in place of `-Register`.
- **Example:** before: nothing open. After: `pdfdesk C1 /A page=323` opens at p. 323.
  `pdfdesk run Pages.Extract C1 --pages 323-328 -o out.pdf` writes 6 pages. **Check:** CLI tests.

### F07 Preferences

- **Foxit** (pp. 23–48): many preference pages.
- **pdfdesk:** the preferences that change behaviour on Linux: documents (restore tabs, redaction file
  name prefix/suffix), page display, full screen, commenting, forms, languages, spelling, OCR, trust
  manager, signature, timestamp servers, identity, speech, search, history. Stored in
  `~/.config/pdfdesk/`.
- **Example:** before: defaults. After: setting the redaction suffix to `_redacted` makes F42 save
  `contract-v1_redacted.pdf`. **Check:** covered by the F42 test.
