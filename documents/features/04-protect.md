# Phase 3 — Protect

Redaction must remove content, not cover it. Every redaction example below is checked by looking for
the removed text in the saved file's text layer and in its raw content streams.

### F40 Mark for redaction

- **Foxit** (p. 323, Business): Protect > Mark for Redaction > Text & Images: drag a rectangle (text
  and images together), double-click an image to mark all of it, or select text. "Place on Multiple
  Pages" copies a mark to the same spot on other pages. Mark for Redaction > Pages marks whole pages in a
  range, with even/odd. Marks show a red outline and fill black on hover. Rectangle marks can be moved and
  resized; text-selection marks cannot.
- **pdfdesk:** PyMuPDF Redact annotations (`add_redact_annot`), one per mark. Text marks use the
  quads of the selected words.
- **Example:** before: C3 v1. After: the client name on p. 1 marked by text selection, the image on p. 6
  marked by double-click, and p. 4 marked as a page. **Check:** three Redact annotations with the expected
  rectangles. The content streams are unchanged until F42.

### F41 Redaction properties and code sets

- **Foxit** (p. 324): Appearance tab: fill colour; overlay text with font, size, colour and alignment;
  custom text; redaction codes chosen from code sets; Edit Codes (add, rename, remove, import, export codes
  and sets). General tab: author, subject. Review History tab. Locked. "Set current properties as
  default". Properties can be changed only before applying.
- **Format:** `Redaction/*.xml` is `<RedactionSet Name="…">` holding `<RedactionCode Name="…"/>`, UTF-8
  with BOM. Foxit ships "U.S. FOIA" (16 codes, `(b) (1) (A)` to `(b) (9)`) and "U.S. Privacy Act"
  (11 codes).
- **pdfdesk:** the Redact annotation's `/OverlayText`, `/IC`, `/DA` and `/Q` hold the appearance.
  pdfdesk ships its own FOIA and Privacy Act sets, written from 5 U.S.C. § 552(b) and § 552a. It can
  import and export sets in Foxit's XML format.
- **Example:** before: the p. 1 mark from F40. After: code `(b) (6)` added, fill black, overlay white.
  **Check:** after F42, the redacted box shows "(b) (6)". Importing Foxit's `U.S. FOIA.xml` gives a set
  with 16 codes in the same order.
- **Open:** where Foxit stores user-edited code sets and its Review History. Black-box: edit a set in
  Foxit and look for the changed file in the Wine prefix.

### F42 Apply redactions

- **Foxit** (p. 325): Protect > Apply Redactions, or Apply / Apply All from the right-click menu. A
  warning asks for confirmation. On save, the file can get a prefix or suffix set in Preferences >
  Documents > Redaction. Cannot be undone after saving.
- **pdfdesk:** PyMuPDF `apply_redactions(images=…, graphics=…, text=…)` removes text under the mark,
  blanks the covered pixels of images, and removes covered vector graphics. Then F46's "deleted content"
  step rewrites the file, so the old content does not survive in an earlier revision.
- **Example:** before: C3 v1 with the three marks from F40 and the code from F41. After: applied and
  saved as `contract-v1_redacted.pdf`. **Check:** `pdftotext` has no client name and no p. 4 text. A search
  of every decompressed stream finds no client-name string. The image on p. 6 is all fill colour where
  marked. The file has a single revision.

### F43 Search and redact

- **Foxit** (pp. 325–326): Protect > Search and Redact in the current file or every PDF in a folder:
  exact word or phrase; multiple words (list with Add, Import and Export of a text file); a redaction
  profile (F44); "Looks like search pattern" with a pattern type and a country/region. Results have
  check boxes, then "Mark Checked Results for Redaction", then Apply.
- **pdfdesk:** the F150 search engine produces hits as quads, which become Redact annotations. Patterns
  are regular expressions grouped by type and country (phone, ID numbers, credit cards with a Luhn
  check, email, dates, postal codes).
- **Example:** before: C3 v1 with an email address and a phone number on p. 2. After: pattern search for
  email and US phone marks both, and nothing else. **Check:** after applying, neither string is in the text
  or the streams.
- **Open:** Foxit's exact pattern list per country, including the Canada patterns added in v10. REA
  string search in `FoxitPhantomPDF.exe` for pattern names and regular expressions, then black-box on a
  test page with near-miss strings to confirm.

### F44 Redaction profiles

- **Foxit** (pp. 326–327): a profile is a named list of word or phrase → overlay text pairs, with Whole
  Words Only, Case-Sensitive, Highlight All Text, and "Always Auto-Size text to fit redaction region".
  Create, Save & Search, Manage (Edit, Delete, Import, Export).
- **pdfdesk:** profiles stored as JSON in `~/.config/pdfdesk/redaction-profiles/`. Import and export in
  Foxit's format once it is known.
- **Example:** before: C3 v1 where "Acme Ltd" appears 4 times. After: a profile mapping "Acme Ltd" →
  "[CLIENT]" with Whole Words marks 4 hits, and the overlay text is auto-sized into each box.
  **Check:** 4 Redact annotations with `/OverlayText` "[CLIENT]"; after applying, "Acme" is gone from the
  text.
- **Open:** Foxit's profile export format. Black-box: export a profile from Foxit and read the file.

### F45 Whiteout

- **Foxit** (p. 323, v10): one step that removes the content under a rectangle and fills it white.
- **pdfdesk:** a Redact annotation with white fill and no overlay, applied at once.
- **Example:** before: C3 v1 p. 2 paragraph 1. After: whiteout over it. **Check:** that paragraph's text
  is gone and the area renders white.

### F46 Remove hidden data

- **Foxit** (p. 322, and the `RemoveHiddenInfo` step in `Action01.sequ` and `Action03.sequ`): items
  `RmAnnots`, `RmAttachments`, `RmBookmarks`, `RmDeletedContent`, `RmFormFields`, `RmHiddenLayers`,
  `RmHiddenText`, `RmLinksActionsJS`, `RmMetadata`, `RmOverlappingObjects`, `RmSearchIndex`. Each is a
  check box. The two shipped actions use different defaults.
- **pdfdesk:** PyMuPDF `scrub` covers attachments, hidden text, JavaScript, links, metadata, XMP and
  form fields. pikepdf covers the rest: comments, hidden layers, overlapping objects (content fully
  covered by an opaque object drawn later), embedded search index, and deleted content (a full rewrite
  with no incremental history).
- **Example:** before: a copy of C1 given an attachment, a note, a hidden layer, white text and an
  author. After: all items except bookmarks. **Check:** each item is absent; bookmarks are kept;
  `pikepdf` finds no `/Prev` in the trailer.

### F47 Password protection

- **Foxit** (pp. 302–305, 307): document-open password, permissions password with print (none, low,
  high), changes, copying, form filling, accessibility, assembly; encryption level (128-bit RC4, 128-bit
  AES, 256-bit AES); encrypt everything, everything except metadata, or attachments only. Security
  policies save a set of these settings under a name for reuse.
- **pdfdesk:** pikepdf `Encryption(R=…, aes=…, metadata=…)` and `Permissions`. Security policies are
  saved settings in `~/.config/pdfdesk/`.
- **Example:** before: C3 v1. After: AES-256 with open password "user1" and owner password "owner1",
  printing low resolution only. **Check:** opening without a password fails; with "user1" pikepdf reports
  R=6, and the permissions allow degraded printing only.
- **Open:** how the `DocSecurity` step in `Action03.sequ` maps to this (`EncryptionMethod=6`,
  `KeyLength=16`, `Revision=4`, `Version=4`, `PDPerms=864`). Black-box: run the action in Foxit and read
  the `/Encrypt` dictionary of the result.

### F48 Certificate protection

- **Foxit** (pp. 305–306): encrypt for a list of recipients' certificates, each with its own
  permissions.
- **pdfdesk:** pyHanko's public-key security handler. pikepdf cannot write this kind of encryption.
- **Example:** before: C3 v1 and two self-signed recipient certificates. After: encrypted for both, with
  recipient 2 unable to print. **Check:** each recipient's key opens the file; recipient 2's permissions
  deny printing; a third key fails.

### F49 Trust settings and safe reading

- **Foxit** (pp. 331–335): Trust Manager (safe reading mode, allowed URLs, trusted files and folders),
  JavaScript on or off, warnings before opening external files or links.
- **pdfdesk:** JavaScript and external actions are off by default; enabling them is per document or per
  folder. Link and launch actions always ask first unless the target is trusted.
- **Example:** before: C4 with a document-open JavaScript action and a Launch action. After: opening runs
  neither and shows a bar offering to enable them. **Check:** test the action dispatcher's log.
