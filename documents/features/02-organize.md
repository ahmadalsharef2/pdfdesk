# Phase 1 — Organize

All of these are PyMuPDF operations unless noted. Each is a command, so it also works in batch and in
the Action Wizard.

### F10 Insert pages

- **Foxit** (pp. 192–194): insert from file, blank page (size, orientation, count), from clipboard, from
  scanner, from web page; before or after a page.
- **pdfdesk:** `insert_pdf` for files (non-PDF files go through F110 first), `new_page` for blank pages.
  Clipboard images and text become a page through F111. Scanner input comes from F32.
- **Example:** before: C3 v1, 6 pages. After: one blank A4 page inserted after p. 2, and C1 pp. 1–3
  inserted at the end, giving 10 pages. **Check:** page count and the text of pp. 8–10 equal C1 pp. 1–3.

### F11 Rotate, move, swap, delete pages

- **Foxit** (pp. 195–196): rotate a range by 90/180/270 (odd, even, all); drag thumbnails to move; swap
  two pages; delete a range.
- **pdfdesk:** `set_rotation`, `move_page`, `delete_pages`. Thumbnail panel supports drag and drop and
  multi-select.
- **Example:** before: C3 v1. After: p. 2 rotated 90°, p. 6 moved to the front, pp. 3–4 deleted.
  **Check:** page order by text and `/Rotate` values.

### F12 Extract, duplicate, replace pages

- **Foxit** (pp. 197–199): extract a range to a new file or one file per page, with "delete pages after
  extracting"; duplicate pages; replace a range with pages from another file.
- **pdfdesk:** `insert_pdf` into a new document; `copy_page`; delete plus insert for replace.
- **Example:** before: C1. After: extract pp. 323–328 as one file per page gives 6 files, each 1 page.
  **Check:** files and their first lines of text.

### F13 Split

- **Foxit** (p. 200): split by number of pages, by file size, or by top-level bookmarks; output folder,
  naming and overwrite options.
- **pdfdesk:** split command with the shared output-options component (F82).
- **Example:** before: C1. After: split by top-level bookmarks gives one file per chapter, each named
  after its bookmark. **Check:** file count equals the number of top-level bookmarks, and page totals add
  up to 446.

### F14 Crop pages

- **Foxit** (pp. 200–201): draw a crop box or set margins; remove white margins; apply to a range or
  odd/even pages; set the crop, art, trim or bleed box.
- **pdfdesk:** `set_cropbox` and the other box setters. "Remove white margins" renders the page and
  finds the content bounds.
- **Example:** before: C1 p. 323, crop box equals media box. After: white margins removed.
  **Check:** the crop box is inside the media box and no text block falls outside it.

### F15 Flatten pages

- **Foxit** (p. 202): flatten annotations and form fields into the page content.
- **pdfdesk:** PyMuPDF `bake(annots=True, widgets=True)`.
- **Example:** before: C4 with filled fields and a note. After: flattened. **Check:** no `/Annots` on any
  page, and `pdftotext` still shows the filled values.

### F16 Reverse pages

- **Foxit** (p. 203): reverse the order of all pages or a range.
- **Example:** before: C3 v1. After: reversed. **Check:** page texts in reverse order.

### F17 Combine files

- **Foxit** (Convert > Combine Files; v10 notes pp. 10–11): add files, folders and open files; reorder;
  convert non-PDF files on the way; options for bookmarks per file, table of contents and page labels.
- **pdfdesk:** `insert_pdf` with `toc` handling. Non-PDF files are converted through F110 first.
- **Example:** before: C3 v1, C4 and `office/letter.docx`. After: one PDF whose top-level bookmarks are
  the three file names, in order. **Check:** page count is the sum of the parts, and the bookmarks point to
  the first page of each part.

### F18 Header and footer

- **Foxit** (pp. 203–207): six positions (left, centre, right × top, bottom); font, size, colour,
  underline; margins; macros for page number ("Page 1 of n" styles) and date formats; page range
  and odd/even; start page number; shrink page content to fit; saved settings; Add, Update, Remove
  All; batch on several files (v10).
- **pdfdesk:** text drawn with PyMuPDF inside a marked-content block tagged as a pagination artifact,
  so Update and Remove All can find exactly what pdfdesk added and nothing else.
- **Example:** before: C1 with no footer. After: "Page 1 of 446" centred at the bottom of every page,
  then Remove All. **Check:** after Add, `pdftotext` of p. 446 ends with "Page 446 of 446". After
  Remove All, the content streams equal the originals.
- **Open:** how Foxit marks its headers and footers, so pdfdesk can update or remove ones that Foxit
  added. Black-box: add a footer in Foxit, then inspect the content stream and `/PieceInfo` with pikepdf.

### F19 Watermark

- **Foxit** (pp. 206–208): text, image or PDF-page source; font, size, colour; rotation, opacity,
  scale relative to page; position and offset; in front of or behind content; show when printing and
  when displaying; page range; Add, Update, Remove All; batch.
- **pdfdesk:** watermark XObject placed on each page, in an optional-content group when "show when
  printing / displaying" differ, marked as a watermark artifact.
- **Example:** before: C3 v1. After: "DRAFT" at 45°, 30 % opacity, behind content, every page.
  **Check:** each page has one watermark XObject; the text layer of body text is unchanged.
- **Open:** Foxit's watermark marking (same black-box run as F18).

### F20 Background

- **Foxit** (pp. 205–206): colour, image or PDF page as background; same placement options as a watermark.
- **Example:** before: C3 v1. After: pale yellow background on all pages, then Remove. **Check:** the
  background is the first drawing operation on each page, and Remove restores the original streams.

### F21 Bates numbering

- **Foxit** (p. 208, Business): Organize > Bates Numbering > Add over files, folders and open files, in
  an order the user sets; output folder, file naming and a log file; then the header/footer dialog with the
  Bates macro: 3–15 digits, increment (negative counts down), start number, rotation, prefix and suffix.
  Numbering continues across files. Remove All removes it. v10 also numbers files from ECM connectors.
- **pdfdesk:** a header/footer (F18) whose text comes from a counter shared across the batch. The
  log lists each file with its first and last number.
- **Example:** before: C3 v1 (6 pages) and C4 (2 pages). After: prefix "ABC", 6 digits, start 1: pages
  read ABC000001 to ABC000008 across both files. The log has two lines. **Check:** text of each page footer,
  and the log contents.

### F22 Page labels

- **Foxit** (p. 209): number ranges in a style (1 2 3, i ii iii, I II III, a b c, A B C, none), with
  start number and prefix; "extend numbering used in preceding section".
- **pdfdesk:** PyMuPDF `set_page_labels`.
- **Example:** before: C1 has no labels. After: pp. 1–6 are i–vi, then 1 onwards from p. 7.
  **Check:** `get_label()` of p. 7 is "1", and of p. 6 is "vi".

### F23 Embed page thumbnails

- **Foxit** (p. 130): embed thumbnails so large files show them faster.
- **pdfdesk:** writes `/Thumb` images with pikepdf. Low priority.
- **Example:** before: C1 with no `/Thumb`. After: each page has a `/Thumb` of at most 106 px on the long
  side. **Check:** pikepdf.
