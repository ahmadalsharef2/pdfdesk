# Phase 2 — OCR, scanning and the PDF Optimizer

### F30 OCR

- **Foxit** (pp. 110–111): detects scanned files on open and offers OCR. Convert > OCR > Current File:
  page range, one or more languages, output "Searchable Text Image" (invisible text under the image)
  or "Editable Text" (image replaced by real text). Quick OCR uses the last settings on every page. OCR
  Multiple Files takes files, folders and open files, with output options. In a portfolio, only the PDFs
  inside are recognised.
- **pdfdesk:** OCRmyPDF with Tesseract for whole files and batches (`--output-type pdf`, `--deskew`,
  `--rotate-pages`), and PyMuPDF `get_textpage_ocr` for one page in the GUI. "Editable Text" rebuilds the
  page as text through the F130 text-setting code, keeping the image of anything that is not text.
  Scanned-file detection: a page with no text and one image covering at least 90 % of the page.
- **Example:** before: C2, 3 pages, `pdftotext` returns nothing. After: OCR with English as searchable
  image. **Check:** `pdftotext` returns text, and at least 95 % of the words of C1 pp. 323–325 are found in
  it. The page images are unchanged byte for byte.
- **Open:** Foxit's scanned-file detection rule. Black-box: open C2 and a born-digital file with one
  full-page photo in Foxit and see which ones get the prompt.

### F31 OCR suspects

- **Foxit** (pp. 111–112): Suspect Results > First Suspect shows each low-confidence word in a red box,
  with the image and the OCR text side by side. Actions: edit the text, Not Text, Find Next, Accept and
  Find. All Suspects (v10) lists every suspect in one dialog for bulk correction. Scope: page or document.
- **pdfdesk:** Tesseract word confidences (from hOCR) are stored in the document as private page data
  while the OCR result is open, and dropped on Save unless the user keeps them. A word below the
  threshold (default 70) is a suspect. Correcting a word rewrites that word in the invisible text layer.
- **Example:** before: C2 after F30. After: the panel lists the suspects. Correcting one changes only that
  word. **Check:** the search text has the corrected word, and every other word is unchanged.

### F32 Scan to PDF

- **Foxit** (pp. 104–107): scan with custom settings (resolution, colour mode, paper size, sides,
  remove blank pages, optimization, OCR) or with a saved preset; insert the result into an open PDF
  (p. 194).
- **pdfdesk:** SANE through `scanimage` (device list, resolution, mode, source including ADF and duplex),
  then F33 on the images. Presets are saved settings.
- **Example:** before: a page in the scanner. After: a searchable PDF. **Check:** a test with SANE's
  `test` backend, which produces a synthetic page without hardware.

### F33 Optimize scanned PDF

- **Foxit** (p. 146 and the "Optimize Scanned Documents" action, `Action05.sequ`): deskew, fix page
  orientation, compress colour and mono images, run OCR, at a quality level. The action's step is
  `Scan:OPT` with `ColorCompression=4 Deskew=1 Format=1 Language=26 MonoCompression=1 QualityLevel=1
  doOCR=true`.
- **pdfdesk:** OCRmyPDF (`--deskew --rotate-pages --optimize 2|3`, with jbig2enc and pngquant).
  `Scan:OPT` maps its integer settings onto these options.
- **Example:** before: C2 (p. 1 skewed 1.5°, p. 2 turned 90°). After: p. 1 is straight within 0.2°, p. 2 is
  upright, text is searchable, and the file is smaller. **Check:** skew measured on the output raster, and
  the orientation reported by Tesseract OSD.
- **Open:** what the integers mean (which compression is 4, which language is 26, which quality is 1).
  Black-box: run the action in Foxit with each value changed in turn. If needed, REA string search in the
  OCR plug-in.

### F34 PDF Optimizer

- **Foxit** (pp. 141–146):
  - **Reduce File Size:** current or multiple files; PDF version compatibility (retain or pick one).
  - **Advanced Optimization:** "Audit space usage" report, then five panels:
    - **Compress Images:** per colour, grey and mono; downsample Off, Average, Subsampling or Bicubic,
      "for images above X ppi" to Y ppi; compression ZIP, JPEG or JPEG 2000 (with tile size) for colour
      and grey; ZIP, JBIG2 lossless or lossy, CCITT G3 or G4, or Run Length for mono; quality Minimum to
      Maximum; "only if smaller". **High Compression** is Business only.
    - **Unembed Fonts:** pick fonts to unembed.
    - **Discard Objects:** form submit/import/reset actions, flatten fields, JavaScript, alternate images,
      thumbnails, tags, merge image fragments (over 25), print settings, search index, bookmarks.
    - **Discard User Data:** comments, forms and multimedia; external cross references; info and
      metadata; attachments; private application data; hidden layers (flatten visible ones).
    - **Clean Up:** Flate for unencoded streams, Flate instead of LZW, invalid bookmarks, invalid links,
      unreferenced named destinations, fast web view.
  - Attachments are never optimized.
- **pdfdesk:** PyMuPDF `rewrite_images` (downsampling and JPEG), `scrub` and `bake`. pikepdf for font
  unembedding, LZW to Flate, object streams, named-destination clean-up and linearization (fast web
  view). jbig2enc for JBIG2. Ghostscript's `pdfwrite` as an optional last pass. High Compression uses
  JBIG2 lossy for text regions and JPEG at low quality for the rest, the closest open-source equivalent.
  The audit counts bytes by object kind (images, fonts, content, forms, structure, other).
- **Example:** before: C1 at 6.4 MB. After: Reduce File Size with defaults gives a smaller file whose
  pages look the same. Then Advanced with colour images bicubic to 150 ppi above 225 ppi and JPEG
  Medium. **Check:** the output is smaller; every image above 225 ppi is now 150 ppi or less; rasters at
  72 dpi differ from the original by no more than a set threshold; attachments are untouched.
