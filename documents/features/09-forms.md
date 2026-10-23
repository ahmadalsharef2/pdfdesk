# Phase 8 — Forms

The first task of this phase is a spike on F90's scripts and F91 (XFA). Both decide which engine fills
forms, so the rest of the phase waits for its result.

### F90 Fill AcroForms

- **Foxit** (pp. 263–266): fill text, check box, radio, combo, list and signature fields; highlight
  fields; auto-complete; reset; field formatting, validation and calculation run as the user types; tab
  order; comment on forms.
- **pdfdesk:** PyMuPDF widgets for values and appearances. Form JavaScript (format, keystroke, validate,
  calculate) needs a JavaScript engine with the Acrobat form API. Two candidates, chosen by the spike:
  - MuPDF's built-in JavaScript, if PyMuPDF exposes it.
  - pypdfium2 on a PDFium build with V8.
- **Example:** before: C4 with `a` and `b` empty. After: typing 2 and 3 sets `total` to 5, and a date
  field formatted `dd/mm/yyyy` rejects "31/02/2026". **Check:** field values after each keystroke event,
  and the regenerated appearance stream shows "5".

### F91 XFA forms

- **Foxit** (Standard feature, p. 7): fill static and dynamic XFA forms.
- **pdfdesk:** PDFium built with XFA support is the only open-source engine for dynamic XFA. Static XFA
  usually carries an AcroForm copy, and pdfdesk fills that and keeps the XFA data stream in step.
- **Example:** before: C5. After: fields filled and saved, then reopened in Foxit. **Check:** the values
  show in Foxit, and the XFA `datasets` stream holds them.
- **Risk:** if no usable XFA-enabled PDFium build exists for Python, dynamic XFA is reported as not
  supported. The spike settles this.

### F92 Create form fields

- **Foxit** (pp. 268–297): push button, check box, radio button, combo box, list box, text field,
  signature field, plus v10's date, image and barcode fields. Properties tabs: General, Appearance,
  Options, Actions, Format, Validate, Calculate. Barcode fields encode other fields' data (QR, PDF417,
  Data Matrix). Align, distribute, centre, match size; duplicate across pages; tab order.
- **pdfdesk:** PyMuPDF `Widget` for the field types; pikepdf for actions and less common dictionary
  keys. Barcode appearance made with segno (QR) and pdf417gen and updated when source fields change.
  Image fields are buttons whose icon is the chosen image.
- **Example:** before: C3 v1 p. 1. After: one field of each type added. **Check:** pikepdf shows the
  expected `/FT` and flags for each field. The QR barcode decodes (with `zbarimg`, if installed) to the
  text field's value.

### F93 Form field recognition

- **Foxit** (p. 269, and the `Adobe:FindsFormFields` action step): find fillable areas on a flat form
  and add fields.
- **pdfdesk:** detection from PyMuPDF `get_drawings` (underlines, boxes, comb boxes, check-box squares)
  and nearby labels from text blocks. Each candidate becomes a field named after its label.
- **Example:** before: a flattened copy of C4 (from F15). After: recognition finds at least 90 % of
  the original fields, with names close to the originals. **Check:** compare field boxes with the original
  C4 boxes by overlap.

### F94 Form data

- **Foxit** (pp. 266–267): import and export form data as FDF, XFDF, XML, CSV and TXT; reset; combine
  data from several forms into one CSV.
- **pdfdesk:** pdfdesk's own FDF and XFDF writers and readers (pikepdf for FDF objects, ElementTree for
  XFDF). CSV has one header row of field names.
- **Example:** before: a filled C4. After: export to XFDF, reset, import. **Check:** values match the
  original. Combining three filled copies gives a CSV with 3 data rows.

### F95 JavaScript

- **Foxit** (pp. 298–301): document JavaScript, field and page actions, JavaScript console, external
  editor (v10), and v10's added functions (page numbering and transitions, search and indexing, web
  links).
- **pdfdesk:** editing scripts is pikepdf work. Running them uses the engine chosen in F90, so the
  console and the added functions depend on that engine's API coverage.
- **Example:** before: C4. After: a document script added through the dialog. **Check:** `/Names
  /JavaScript` holds it, and with JavaScript allowed (F49) it runs on open.
