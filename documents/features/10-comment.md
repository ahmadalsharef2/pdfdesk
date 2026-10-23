# Phase 9 — Comments

All annotation types are PyMuPDF annotations unless noted. Each one writes a correct appearance stream,
so other viewers show it the same way.

### F100 Text markup

- **Foxit** (pp. 210–212): highlight, underline, squiggly, strikeout, replace text (strikeout plus
  inserted note), insert text (caret).
- **Example:** before: C1 p. 323. After: one of each on the first paragraph. **Check:** six annotations
  of the expected subtypes, with quads over the selected words.

### F101 Pin tools

- **Foxit** (pp. 212–213): note, file attachment, audio (record or attach).
- **pdfdesk:** Text and FileAttachment annotations. Audio recording through Qt Multimedia to a WAV file
  embedded in a Sound annotation, played back by the system player.
- **Example:** before: C1 p. 1. After: a note and an attached `office/letter.docx`. **Check:** the
  attachment extracts byte for byte.

### F102 Typewriter, text box, callout

- **Foxit** (pp. 213–216): typewriter (no border), text box, callout with leader line; fonts and
  alignment; Hindi digits option (v10).
- **pdfdesk:** FreeText annotations with intents `FreeTextTypeWriter` and `FreeTextCallout`.
- **Example:** before: C7. After: a typewriter comment in Arabic. **Check:** the text reads back
  identical and renders right to left.

### F103 Drawing

- **Foxit** (pp. 216–219): line, arrow, rectangle, oval, polygon, polyline, pencil, eraser, cloud,
  area highlight.
- **pdfdesk:** Line, Square, Circle, Polygon (with cloudy border effect), PolyLine and Ink annotations.
  The eraser removes points from Ink annotations.
- **Example:** before: C1 p. 2. After: one of each. **Check:** subtypes and the cloud's `/BE` dictionary.

### F104 Measure

- **Foxit** (pp. 219–223): distance, perimeter and area, with a scale ratio and units, snapping to
  paths, endpoints, midpoints and intersections; results shown in a Format panel and saved as comments.
- **pdfdesk:** Line, PolyLine and Polygon annotations with a `/Measure` dictionary written through pikepdf.
  Snap points from `get_drawings`.
- **Example:** before: C3 v1 p. 4 (a table). After: with scale 1 in = 1 ft, a distance across the table's
  width. **Check:** the label equals the width in points × scale, and `/Measure` holds the ratio.

### F105 Stamps

- **Foxit** (pp. 223–227): standard, sign-here and dynamic stamps (name and date filled in); custom
  stamps from images or PDF pages; stamp palette; paste a clipboard image as a stamp. Shipped stamp sets
  are in `stamps/<lang>/*.pdf` and `stamps/Standard Templates/`.
- **pdfdesk:** Stamp annotations whose appearance is a PDF page or an image. pdfdesk draws its own stamp
  set. Foxit's stamp files can be imported from the user's install.
- **Example:** before: C3 v1. After: an "APPROVED" dynamic stamp showing the user name and today's date.
  **Check:** the appearance stream text contains both.
- **Open:** how Foxit's stamp PDFs mark each stamp (page names, dynamic fields). Read with pikepdf from
  `stamps/en-US/Dynamic Stamps.pdf`. This is format data, not code.

### F106 Appearance and properties

- **Foxit** (pp. 228–230): colour, opacity, line style and width, fill, fonts; "set as default";
  locked; v10's option to show all comments in one font of the user's choice.
- **Example:** before: a red rectangle. After: blue, 50 % opacity, dashed, set as default; the next
  rectangle is blue too. **Check:** `/C`, `/CA` and `/BS` values.

### F107 Manage comments

- **Foxit** (pp. 230–240): Comments panel with sort, filter, search, expand and collapse; reply;
  status (accepted, rejected, cancelled, completed) and check marks; show and hide by type or
  author; Keep Tool Selected; summarize comments (p. 235).
- **Foxit's summary** (`CommentsSummary.fpi`) has four layouts:
  - Comments only.
  - Document and comments with connector lines on a single page.
  - Document and comments with connector lines on separate pages.
  - Document and comments with sequence numbers on separate pages.

  It also has paper size, sorting, font size and a page range.
- **pdfdesk:** reply threads use `/IRT`; status uses state annotations (`/State`, `/StateModel`). The
  summary is built as a new PDF in each layout.
- **Example:** before: C1 with 10 comments by 2 authors on 3 pages. After: a summary in each layout.
  **Check:** each summary lists 10 comments in sort order; the connector-line layouts draw 10 lines.
- **Foxit check:** summarize the same file in Foxit and compare the layout.

### F108 Import and export comments

- **Foxit** (pp. 237–238): import and export comments as FDF and XFDF; export comments to Word; send
  comments by email; import comments from another PDF.
- **pdfdesk:** the same FDF and XFDF code as F94. "Export comments to Word" writes a `.docx` list of
  comments with python-docx.
- **Example:** before: C1 with 10 comments. After: export to XFDF, delete all, import. **Check:** the 10
  comments are back with the same subtypes, rectangles, authors and text.
