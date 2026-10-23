# Phase 12 — Search, index, accessibility, read aloud

### F150 Advanced search

- **Foxit** (pp. 76–83, v10 notes p. 10):
  - Where: the current document, all PDFs in a folder, or an index.
  - Criteria: exact phrase, any of the words, all of the words (index only), and "looks like" patterns
    (not with indexes).
  - Options: whole words, case-sensitive, include bookmarks, comments and attachments; v10 adds
    proximity, word stems, ignoring Asian character width, and ignoring diacritics and accents.
  - A cache makes repeat searches faster.
  - Results are grouped by file and page, and "highlight all" marks them.
- **pdfdesk:**
  - The current document is searched directly on PyMuPDF text pages.
  - Folders and indexes use SQLite FTS5 with the `porter` and `unicode61 remove_diacritics` tokenizers.
    Tested here on SQLite 3.45.1: stemming and `NEAR` proximity work.
  - Asian width folding is done by NFKC normalisation before indexing.
  - The cache is the same FTS5 database, kept per folder.
- **Example:** before: a folder holding C1, C3 v1 and C3 v2. After: searching "redact" with word stems
  finds "redaction", "redacted" and "Redact" in C1. "contract NEAR/5 payment" finds the clause in both C3
  files. **Check:** hit counts against a brute-force count of the extracted text.

### F151 Search patterns

- **Foxit** (pp. 76–78, 325–326): phone number, social security number, email address, credit card,
  dates and more, chosen by type and country/region. v10 adds Canada patterns. The same patterns serve
  Search & Redact (F43).
- **pdfdesk:** a table of regular expressions by type and country, with checksums where they exist
  (Luhn for cards, the SIN check for Canada).
- **Example:** before: a test page with 10 real-format and 10 near-miss strings per pattern. After: each
  pattern finds exactly its 10. **Check:** the hit lists.
- **Open:** Foxit's exact list of types and countries (see F43).

### F152 Full-text index

- **Foxit** (pp. 35–36, 81–83): create, rebuild and purge a catalog index over folders; include and
  exclude folders; options for custom properties, XMP and long file names (v10). A batch XML file lists
  indexes and flags for scheduled updates by Task Scheduler (v10). Search uses the index.
- **pdfdesk:** an FTS5 database file per catalog. Rebuild is incremental by file modification time.
  The batch file is read in Foxit's format once that format is known. Scheduling uses a systemd user
  timer, the Linux stand-in for Task Scheduler.
- **Example:** before: a folder of 50 copies of corpus files. After: build the index, change one file,
  update. **Check:** only that file is re-indexed (log), and a search returns its new text.
- **Open:** the batch XML format. Black-box: let Foxit write one, or read the example in the manual's
  index section.

### F153 Accessibility check and fix

- **Foxit** (pp. 355–363):
  - A Full Check with rule categories: document, page content, forms, tables and lists, alternate text,
    headings.
  - Results in an Accessibility Check panel, with Fix, Skip Rule, Explain and Check Again for each item.
  - An optional report.
  - Fixing is Business only.
- **Rules:** the `AccCheck:DoCheck` step in `Action02.sequ` names 32 rule switches: `Color`, `CharEnc`,
  `TaggedContents`, `ImageOnly`, `Tagged`, `Annots`, `FieldNames`, `Forms`, `Headings`, `TableTHTD`,
  `FigureAltText`, `Bookmark`, `FlickerRate`, `PermCheck`, `TableSummary`, `TabOrder`, `ContentAltText`,
  `NestedAltText`, `DocTitle`, `TableRegularity`, `ListItems`, `NavigationLinks`, `TableRows`,
  `Scripts`, `LangSpec`, `Multimedia`, `LogicalReadingOrder`, `AnnotAltText`, `TableHeaders`,
  `LblLBody`, `ElementAltText`, `TimedResponses`. These are the same rule names as Acrobat's
  accessibility checker.
- **pdfdesk:** each rule is a check over the structure tree, content marking and catalog, read with
  pikepdf. Rules that cannot be decided by machine (`Color`, `LogicalReadingOrder`, `FlickerRate`,
  `TimedResponses`, `Scripts`) are reported as "needs manual check", as Acrobat does. veraPDF's PDF/UA
  profile runs alongside. Fixes cover the decidable rules: set title and display title, set language,
  set tab order to structure, add bookmarks from headings, mark untagged content as artifacts, add
  alternate text with a prompt.
- **Example:** before: C1 (untagged). After: the check fails `Tagged`, `DocTitle` display, `LangSpec` and
  `Bookmark` is passed, and the rest are listed. Running the fixes for `DocTitle` and `LangSpec` turns them
  green. **Check:** rule results before and after.

### F154 Create accessible PDFs

- **Foxit** (pp. 366–379, Business): auto-tag a document (also as a batch through the "Make
  Accessible" action); Reading Order tool (tag regions as text, figure, table, heading levels and more;
  fix the order); Tags panel (edit the tag tree, properties, alternate text); set alternate text for
  figures; set reading language; set tab order; check and fix reflow problems (p. 374).
- **pdfdesk:** auto-tagging from layout analysis:
  - PyMuPDF blocks give paragraphs.
  - Font size and weight rank headings H1–H6.
  - `find_tables` gives tables (TR, TH, TD).
  - Images give figures.
  - Running headers and footers become artifacts.
  - Block order gives reading order, with a columns check.

  pikepdf writes the structure tree, `/StructParents` and the marked-content IDs. The Reading Order tool
  and the Tags panel edit the same tree. Weaker than Foxit, as the plan says.
- **Example:** before: C3 v1 (untagged). After: auto-tag. **Check:**
  - The structure tree holds an H1 for the title, P elements for the paragraphs, a Table with 1 header
    row on p. 4, and a Figure on p. 6.
  - All page content is either tagged or an artifact.
  - veraPDF's PDF/UA checks pass, except figure alternate text, which needs a person to write it.

### F155 Accessible reading

- **Foxit** (pp. 364–365): reflow view (also for reading tagged PDFs); document colour replacement
  (high contrast); reading order options; keyboard navigation; screen reader support.
- **pdfdesk:** a reflow view built from the tag tree when one exists, otherwise from blocks. Colour
  replacement changes the render colours. Screen readers get access through Qt's accessibility bridge
  (AT-SPI). The JAWS scripts in Foxit's plug-in folder have no Linux equivalent.
- **Example:** before: C3 v1 after F154. After: reflow view at 200 % shows paragraphs in reading order
  with no horizontal scrolling. **Check:** the order of the view's text equals the structure-tree order.

### F156 Read Out Loud

- **Foxit** (p. 69, shortcuts p. 445): read the current page, or from the current page to the end;
  pause, stop; voice, pitch, volume and speed, using installed voices.
- **pdfdesk:** speech-dispatcher, which works here through its espeak-ng module. Piper (better voices)
  has a launcher in `~/.local/bin`, but the `piper` Python module is missing (`ModuleNotFoundError`), so
  it must be reinstalled before pdfdesk can offer it. The text order comes from F155.
- **Example:** before: C1 p. 323. After: reading starts at the first heading and the word being spoken
  is highlighted. **Check:** the sequence of text sent to speech-dispatcher equals the page's
  reading-order text.
