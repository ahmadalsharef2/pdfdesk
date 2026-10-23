# Phase 5 — Industry standards: preflight, PDF/A, PDF/E, PDF/X, PDF/UA

Foxit's preflight is the callas engine: `plugins/PDFA/pdfEngineLight.dll`, and the step name
`CALS:Preflight` in `Action06.sequ` with profile key `P_8_ConverttoPDFA1b`. pdfdesk does not use callas.
It uses veraPDF for validation and Ghostscript or OCRmyPDF for conversion, with its own checks where those
two stop.

### F60 Preflight

- **Foxit** (pp. 113–116):
  - Profiles tab: libraries of profiles, single checks and single fixups; favourites; find; page range.
    A filled wrench marks a profile that has fixups. Buttons: Analyze, Analyze and fix, Fix.
  - Results tab: green check, red X, blue info, wrench (fixed) and wrench with X (fix failed). Create
    Report as PDF, XML, TXT or HTML. A PDF report has Overview and Details, with problems highlighted by
    transparent masks or by layers.
  - Standards tab: a wizard for PDF/A, PDF/E and PDF/X.
- **pdfdesk:**
  - Validation: veraPDF for PDF/A-1/2/3/4 (a, b, u) and PDF/UA-1/2.
  - pdfdesk's own checks, written in pikepdf, for what veraPDF does not cover: fonts embedded, PDF
    version, transparency, colour spaces and output intent, image resolution, encryption, JavaScript,
    page boxes.
  - Fixups: conversion steps (F61), font embedding through Ghostscript, and metadata repair.
  - The PDF report draws problem areas as a transparent mask or puts them on a layer.
- **Example:** before: C1, which is not PDF/A. After: the "Verify compliance with PDF/A-2b" profile
  reports errors, including missing XMP PDF/A identification and missing output intent. Analyze and fix
  produces a file that veraPDF passes. **Check:** veraPDF's XML result for the fixed file says compliant,
  and the report PDF opens with a mask on each problem page.
- **Open:** Foxit's profile list (names and groups), so the libraries look the same. Source: the
  `plugins/PDFA/var` folder. Read it as data first, and use REA only if it is binary.

### F61 Convert to PDF/A, PDF/E, PDF/X

- **Foxit** (pp. 116–118, Business): through the Standards wizard, a preflight profile, or Save As.
  Standard edition only validates.
- **pdfdesk:**
  - PDF/A-1b, 2b, 2u, 3b and 3u through Ghostscript (`-dPDFA=n`, ICC output intent). OCRmyPDF is used
    when OCR also runs.
  - PDF/A-1a, 2a and 3a also need tags, so they depend on F154.
  - PDF/X-3 and PDF/X-4 through Ghostscript with an output intent; X-1a converts colours to CMYK.
  - PDF/E-1: PDF/A-style rules plus 3D rules, set by pdfdesk's own fixups and checks. Weak, as noted in
    the plan.
- **Example:** before: C3 v1. After: Save As PDF/A-2b. **Check:** veraPDF says compliant, and the XMP has
  `pdfaid:part=2` and `pdfaid:conformance=B`.
- **Example 2:** before: C1. After: run Foxit's own `Action06.sequ` ("Archive Documents") through F80.
  **Check:** veraPDF passes the output as PDF/A-1b.

### F62 Standard-compliant documents on open

- **Foxit:** a document that claims PDF/A opens with a bar saying so. Editing it would break compliance.
- **pdfdesk:** reads the XMP claim and shows a bar with a "Verify" button that runs F60, and an
  "Enable editing" button.
- **Example:** before: the F61 output. After: opening shows the bar. **Check:** GUI test.

### F63 PDF/UA

- **Foxit:** PDF/UA checks come through preflight (p. 113) and the accessibility checker (F153).
- **pdfdesk:** veraPDF PDF/UA profile, presented with the F153 results.
- **Example:** covered by F153's example.
