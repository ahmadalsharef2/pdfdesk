# Phase 11 — Edit

This phase holds the hardest work in the plan. Editing content that already exists (F130–F135) needs
an object-level editor for content streams, built on pikepdf. It:

1. Parses a page's operators.
2. Maps each text, image and path object to its range of operators.
3. Rewrites that range: wraps it in a transform, changes its colour, deletes it, or splits or merges
   `BT … ET` blocks.

PyMuPDF supplies the object geometry: `get_texttrace` for text, `get_image_info` for images,
`get_drawings` for paths.

### F130 Edit text objects

- **Foxit** (pp. 163–164): Edit Object > Text: click into a text object and change its text, font,
  size, colour, spacing, scaling, underline and strikeout. Hindi digits (v10).
- **pdfdesk:**
  1. Remove the old glyphs with a text-only redaction: `apply_redactions(images=0, graphics=0, text=0)`.
  2. Write the new text in the same font when the embedded font has the needed glyphs. The font
     program comes from PyMuPDF `extract_font`.
  3. Otherwise, use the closest installed font found through fontconfig.
- **Example:** before: C3 v1 p. 2, "net 30 days". After: changed to "net 45 days". **Check:** the
  page text has the new string. Its font name and size equal the old run's. A raster diff outside that
  line's box is zero.

### F131 Paragraph editing and reflow editing

- **Foxit** (pp. 154, 164–165): Edit Text works on paragraph boxes, where text reflows inside the box as
  you type. Reflow Editing reflows the content of a whole page.
- **pdfdesk:** paragraphs are built from PyMuPDF blocks and lines. An edit removes the paragraph's
  glyphs (as in F130), then sets the new text in the same box with `insert_htmlbox`, using the
  paragraph's font, size, line spacing and alignment. Text that no longer fits grows the box downwards
  and warns if it would overlap content below. Weaker than Foxit, as the plan says.
- **Example:** before: C3 v1 p. 3 paragraph 2 (5 lines). After: a sentence inserted in the middle; the
  paragraph rewraps to 6 lines inside the same width. **Check:** the text is in reading order, the box
  width is unchanged, and nothing overlaps the next paragraph.

### F132 Search and replace text

- **Foxit** (p. 153): find text and replace one or all, with match case and whole words.
- **pdfdesk:** F150 search, then F130 on each hit.
- **Example:** before: C3 v1, with "Acme Ltd" 4 times. After: "Replace All" with "Acme GmbH".
  **Check:** 4 replacements, and no "Acme Ltd" left.

### F133 Add text

- **Foxit:** add new text objects anywhere, in any installed font.
- **pdfdesk:** PyMuPDF `insert_text` / `insert_htmlbox`; full fonts are embedded and then subset with
  `subset_fonts`.
- **Example:** before: C7. After: an Arabic line added under the existing text. **Check:** it reads back
  in the same logical order, and the font is embedded.

### F134 Objects

- **Foxit** (pp. 155–179):
  - Select text, image and shape objects; move, resize, rotate, flip.
  - Align, centre and distribute; arrange front to back; properties.
  - Business only: shear and clip (p. 166), merge and split text objects (p. 163), convert text to
    shapes (p. 164), add new image objects (p. 156), add new shape objects (p. 157).
- **pdfdesk:** the object editor described at the top of this file. "Convert text to shapes" draws the
  glyph outlines from the font as paths. New shapes and images are appended as new objects.
- **Example:** before: C3 v1 p. 6, image at the top right. After: moved 50 pt left, rotated 10°, sheared
  15°, and clipped to its lower half. **Check:** the image's transform matrix equals the expected product.
  The clip path is present. Nothing else on the page changed (raster diff outside the old and new
  boxes).

### F135 Image editor

- **Foxit** (pp. 171–179, Business): edit an image in place: select, crop, rotate, flip; brush, eraser,
  fill, clone stamp; brightness, contrast, hue and saturation; save back into the PDF.
- **pdfdesk:** an editor window in Qt working on a Pillow image, written back with PyMuPDF
  `replace_image`.
- **Example:** before: C3 v1 p. 6 image. After: brightness +20 %, then saved. **Check:** the image xref's
  new pixels equal the expected Pillow result, and its placement is unchanged.

### F136 Edit scanned PDFs

- **Foxit** (v10 notes p. 11): edit text on a scanned page.
- **pdfdesk:** F30 "Editable Text" first, then F130 and F131.
- **Example:** before: C2 p. 1. After: OCR, then one word changed. **Check:** the word is real text in
  the page's font, and the rest of the page image is unchanged.

### F137 Links

- **Foxit** (pp. 119–124): rectangle and quadrilateral links; actions go to a page view, open or launch
  a file, open a web page, run JavaScript, and more; appearance; create links from URLs found in the
  text; remove all links.
- **pdfdesk:** PyMuPDF `insert_link` and the link API; pikepdf for less common actions.
- **Example:** before: C3 v1 with plain-text URLs. After: "Create links from URLs". **Check:** each URL
  string has a URI link over its box.

### F138 Bookmarks

- **Foxit** (pp. 125–128): add, nest, rename, reorder, delete; actions; colour and bold or italic;
  bookmarks from document structure; expand to the current bookmark; v10 tag integration.
- **pdfdesk:** PyMuPDF `get_toc`/`set_toc`, with pikepdf for colours, styles and actions.
- **Example:** before: C1. After: one bookmark moved under another and made red and bold. **Check:**
  the outline tree and the bookmark's `/C` and `/F` values.

### F139 Destinations

- **Foxit** (p. 130): named destinations panel; create, rename, delete, sort.
- **Example:** before: C1. After: destination "redaction" set to p. 323 and linked from p. 1.
  **Check:** `/Dests` has the name, and the link resolves to p. 323.

### F140 File attachments

- **Foxit** (pp. 131–133): document-level attachments panel; add, open, save, delete, description;
  attachments as comments (F101).
- **pdfdesk:** PyMuPDF `embfile_*`.
- **Example:** before: C3 v1. After: `office/budget.xlsx` attached with a description. **Check:** it
  extracts byte for byte, and the description is kept.

### F141 Images

- **Foxit** (pp. 134–140): add an image; image properties; export an image; image markups.
- **pdfdesk:** PyMuPDF `insert_image` and `extract_image`.
- **Example:** before: C3 v1 p. 1. After: a logo inserted top left at 2 cm wide. **Check:** image
  placement and size.

### F142 Articles

- **Foxit** (pp. 180–183): define article threads across boxes on pages; read along a thread; edit,
  delete.
- **pdfdesk:** `/Threads` and `/B` beads written through pikepdf. The viewer follows beads.
- **Example:** before: C3 v1. After: a 3-bead article over pp. 1–3. **Check:** the thread has 3 beads in
  order with the drawn boxes.

### F143 Spelling check

- **Foxit** (p. 184): spelling check in comments, form fields and edited text, as you type and on
  demand; add words to a dictionary.
- **pdfdesk:** Hunspell dictionaries through spylls, or pyenchant. Arabic and German dictionaries are
  installed. English needs `hunspell-en-us`.
- **Example:** before: a comment "teh contract". After: "teh" underlined, with "the" first among the
  suggestions. **Check:** the checker's result for that string.

### F144 Layers

- **Foxit** (pp. 185–188): show and hide layers; layer properties (default state, print and export
  behaviour, locked); add content to a layer. Business only: import a file as a layer, merge layers,
  flatten layers.
- **pdfdesk:** PyMuPDF optional content (`add_ocg`, `get_ocgs`, layer configurations). Import uses
  `show_pdf_page` with the new layer. Merge and flatten rewrite the `/OC` references in marked content
  through pikepdf; flattening removes the content of hidden layers.
- **Example:** before: C3 v1. After: C1 p. 1 imported as layer "Overlay" on p. 1, then merged into a layer
  "Base", then flattened. **Check:** the layer list after each step, and after flattening there is no
  `/OCProperties`, while the visible content is unchanged.

### F145 Video and audio

- **Foxit** (pp. 149–152): play multimedia (with a trust prompt); add video and audio to a page; set
  properties (play area, poster, controls, playback).
- **pdfdesk:** playback through Qt Multimedia, after the trust check (F49). Adding media writes Screen
  and RichMedia annotations through pikepdf.
- **Example:** before: C3 v1. After: an MP4 added on p. 1 with a poster image. **Check:** the annotation
  and the embedded media stream are present, and the media extracts byte for byte.

### F146 Document properties and initial view

- **Foxit** (pp. 189–191, and the `GeneralInfo` and `OpenInfo` action steps): title, author, subject,
  keywords, custom properties, XMP; initial view (layout, magnification, page, window options, display
  title); fonts list; reading direction; base URL; trapped.
- **pdfdesk:** PyMuPDF `set_metadata`, `set_xml_metadata`, and the catalog's `/PageLayout`, `/PageMode`,
  `/OpenAction` and `/ViewerPreferences`. `OpenInfo`'s `LeaveAsIs` group says which keys to keep as they
  are.
- **Example:** before: C1. After: the `OpenInfo` step from `Action02.sequ`. **Check:**
  `/ViewerPreferences /DisplayDocTitle true`, and the other keys are unchanged, as `LeaveAsIs` says.
