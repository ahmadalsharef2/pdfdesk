# Phase 10 — Create and export

### F110 Create a PDF from a file

- **Foxit** (p. 87; Office pp. 93–100): drag a file onto the window or icon; any printable file; from Office (Word,
  Excel, PowerPoint, Outlook, Visio and Project in Business); Office add-in tabs with settings (bookmarks
  from headings, links, comments, document properties, tags).
- **pdfdesk:** LibreOffice headless (`soffice --convert-to pdf` with export filter options for
  bookmarks, links, tags and comments) for office formats, including `.vsdx` and `.vsd`. img2pdf for
  images, PyMuPDF for text files, F112 for HTML. A creation preset (F114) is applied afterwards.
  Microsoft Project is not built (see the plan).
- **Example:** before: C6. After: four PDFs. `letter.docx` keeps its headings as bookmarks and its links
  as links. **Check:** page counts, bookmark titles equal the heading texts, and `get_links()` returns the
  link targets.

### F111 Blank page, clipboard, combine

- **Foxit** (p. 91): blank PDF (size, orientation, pages); PDF from clipboard (image or text); combine
  files (F17).
- **Example:** before: an image on the clipboard. After: a one-page PDF sized to the image.
  **Check:** page size equals the image size at its dpi.

### F112 Web pages

- **Foxit** (pp. 91–92, browsers p. 103; `plugins/Creator/AcqWeb.exe`, `html2pdf`): URL, levels to capture or
  whole site, stay on the same path or the same server; page size, orientation, margins, headers and
  footers, links kept and turned into PDF links, bookmarks per page. Browser add-ins convert the current
  page.
- **pdfdesk:** Playwright with headless Chromium prints each page to PDF. A crawler follows links to the
  set depth inside the allowed scope. Links between captured pages are rewritten as internal PDF links,
  and each page gets a bookmark with its title.
- **Example:** before: a small local test site (3 pages linked in a chain), served by
  `python -m http.server`. After: depth 2 captures all 3. **Check:** 3 bookmarks; the link on page 1 jumps
  to page 2 inside the PDF.

### F113 Virtual printer

- **Foxit** (p. 101; printer properties pp. 386–390): "Foxit PhantomPDF Printer" prints from any application to PDF.
  Printer properties: General (paper, orientation, PDF version, fast web view, document info), Image
  compression, Fonts, Watermark, Header & Footer, Security, USPTO; presets.
- **pdfdesk:** a CUPS queue "pdfdesk" using the cups-pdf backend. A small user service watches the
  output folder, applies the chosen preset (F114) and opens the result in pdfdesk.
- **Example:** before: none. After: printing a LibreOffice document to "pdfdesk" with the "Smallest File
  Size" preset opens a PDF whose images are 100 ppi or less. **Check:** image resolution in the output.

### F114 Creation presets

- **Foxit** (`Setting/*.xml`): Standard, High Quality Print, Smallest File Size, PDF A-1b, USPTO. Format:
  - `<FXCreatorData>` holds:
    - `<Standard PDFIndustryStandard PDFStandard>`
    - `<General PDFVersion bWebView …>`
    - `<Image_C>`, `<Image_G>` and `<Image_M>` (colour, grey, mono) with `compressAlg`,
      `compressQuality`, `DestPPI`, `SrcPPI` and `StretchFlag`
    - `<Font FontWarnMsg FontEmbed FFaces>`
    - `<HF …>` for header and footer
    - `<PRT EncryptType>`
    - `<WM …>` for the watermark
    - `<Description Desc>`
    - `<USPTO uspto>`, only in the USPTO preset
  - A `<Sign>` element with a base64 value follows the root element. The file therefore has two
    top-level elements and is not well-formed XML.
- **pdfdesk:** reads these files by wrapping them in a temporary root. pdfdesk ignores `<Sign>`; it
  neither checks nor writes Foxit's signature. Its own presets use the same fields in a JSON file.
  `SrcPPI`/`DestPPI` mean "downsample images above SrcPPI to DestPPI", matching F34.
- **Example:** before: C6 `letter.docx` with a 600 ppi photo. After: converted with Foxit's own
  `Standard.xml` read by pdfdesk. **Check:** the photo is downsampled to 150 ppi, because 600 is above the
  `SrcPPI` of 225.
- **Open:** what the `compressAlg` codes (4, 16, 64), the `compressQuality` codes (2, 4, 16, 32), the
  `StretchFlag` value 128, `FontEmbed=2` and the `PDFStandard` values mean. Black-box: print the same page
  through Foxit's printer with each preset and read the image filters and fonts with pikepdf.

### F115 PDF portfolios

- **Foxit** (pp. 107–110): create from files and folders; layouts; cover sheet (`coversheet/<lang>/`);
  columns (name, size, modified, description, custom fields); sort and order (v10); add, extract and
  remove files; reduce the size of PDFs inside (v10); search inside; OCR inside (F30).
- **pdfdesk:** embedded files plus a `/Collection` dictionary written through pikepdf, with pdfdesk's own
  cover sheet. In the viewer, a portfolio opens as a file list with the chosen columns.
- **Example:** before: C3 v1, C4 and `office/budget.xlsx`. After: a portfolio sorted by name with a
  "Client" custom column. **Check:** `/Collection /Schema` has the column, there are 3 embedded files, and
  the sort key is name.

### F116 Table of contents from bookmarks

- **Foxit** (pp. 112–113): new TOC pages at the start, from all or chosen bookmark levels, numbered 1,
  1.1, 1.2 and so on, up to 5 indented levels by default. When combining files, each file name is a
  first-level heading.
- **Example:** before: C1 with its bookmarks. After: TOC pages are inserted at the front, and each
  entry links to its page. **Check:** the entry count equals the bookmark count for the chosen levels, and
  the links point to the bookmark targets, shifted by the number of TOC pages.

### F117 Export to Word and RTF

- **Foxit** (p. 52): page range; include comments and images; layout "retain flowing text" or
  "retain page layout"; "Image-based document" engine runs OCR first.
- **pdfdesk:** pdf2docx for `.docx`. LibreOffice converts that to `.rtf` and `.odt`. Image-based files run
  F30 first. Comments are added as Word comments with python-docx.
- **Example:** before: C3 v1. After: `.docx`. **Check:** the docx text, read with python-docx, has at
  least 98 % of the PDF's words in the same order. The table on p. 4 is a Word table with the same cell
  values.

### F118 Export to Excel

- **Foxit** (p. 53): tables to sheets, with options for one sheet per page or one per table.
- **pdfdesk:** PyMuPDF `find_tables` (pdfplumber when that fails) to openpyxl.
- **Example:** before: C3 v1 p. 4. After: `.xlsx`. **Check:** the cell values equal the PDF table.

### F119 Export to PowerPoint

- **Foxit** (p. 52): one slide per page with editable text.
- **pdfdesk:** python-pptx: the page drawn without text as the background, with the text blocks as text
  boxes on top. Weak, as the plan says.
- **Example:** before: C3 v1. After: `.pptx` with 6 slides. **Check:** slide count, and each slide's text
  boxes hold that page's text.

### F120 Export to images, HTML, XPS, text, XML

- **Foxit** (pp. 52–56): PNG, JPEG, JPEG 2000 and TIFF with resolution and colour settings (p. 56);
  export all images (p. 56); HTML (p. 55); XPS (p. 54); plain text (p. 52); XML.
- **pdfdesk:** PyMuPDF rendering and `get_text("html" | "text" | "xml")`, Pillow for TIFF and JPEG 2000.
  The XML export is a tagged-structure dump; its schema is open. No open-source library writes XPS, so
  pdfdesk writes the XPS package itself: one fixed page per PDF page, each holding a rendered image of
  that page. The text is not selectable in it.
- **Example:** before: C1 pp. 1–3. After: PNG at 150 dpi gives 3 files of 1240 × 1754 px. Export all
  images writes every embedded image once. **Check:** sizes, and image count equals unique image xrefs.
- **Open:** Foxit's XML export schema. Black-box: export C3 v1 to XML in Foxit.

### F121 File manager integration

- **Foxit:** shell extension (convert to PDF, combine, open) and an IFilter for Windows Search.
- **pdfdesk:** a `.desktop` file with actions for "Convert to PDF" and "Combine in pdfdesk", and Nautilus
  scripts. The desktop's own indexer already reads PDFs, so no search filter is needed.
- **Example:** before: `office/letter.docx` in the file manager. After: right-click > Convert to PDF
  writes `letter.pdf` next to it. **Check:** the file exists and opens.
