# Phase 4 — Compare

### F55 Compare two PDFs

- **Foxit** (pp. 84–86):
  - View > Compare: choose Old File and New File (local or from a connector), preview pages, pick page
    ranges.
  - Options:
    - Include: Compare Text Only, Compare Table, Detect Page Deletions or Inserts.
    - Markup colour, opacity and line thickness for replaced, inserted and deleted items.
    - "Set current properties as default".
  - Comments are not compared.
  - The result opens as a new document, "The result of Comparison.pdf":
    - Page 1 summarises the counts and marks for each kind of change.
    - Page 2 gives the details: names and sizes of both files, time compared, the classification of
      changes, a colour legend, and a "Go to the First Change (page n)" link.
    - The remaining pages show Old and New side by side, with each change marked.
  - A Compare Results ribbon tab offers Next/Previous Change, a Filter (text, images, annotations,
    formatting, everything) and Show (results, legend, summary).
  - Each change is also a comment, so the Comments panel lists them and clicking one finds it in both
    files.
  - Foxit ships `CompareTamplateFile/old summary.pdf`, `new summary.pdf` (A4, one page each) and
    `summary Legend.pdf` (75 × 95 pt) as building blocks for the result.
- **pdfdesk:**
  1. Extract words with PyMuPDF from both files, keeping page, box, font, size and colour for each word.
  2. Diff the two word streams for the whole document, not page by page, with `difflib.SequenceMatcher`.
     This lets an inserted or deleted page show up as one change, as "Detect Page Deletions or Inserts"
     requires.
  3. Classify each change:
     - Same words with a different font, size or colour → formatting change.
     - Changed words → replacement.
     - Words only in New → insertion.
     - Words only in Old → deletion.
  4. Match images by content hash and position: same hash in a new place → moved; hash changed in the
     same place → image replaced.
  5. Compare tables cell by cell after table detection (`find_tables`).
  6. Build the result with `show_pdf_page` (Old left, New right), add the summary and detail pages, and
     add one comment per change with colours from the options. Filters show or hide comments by kind.
- **Example:** before: C3 v1 and v2, with five known edits. After: the result's summary lists exactly 1
  replacement (p. 2), 1 insertion (p. 3), 1 table change (p. 4), 1 deleted page (p. 5) and 1 image change
  (p. 6), with no other changes. **Check:** the change list equals the expected five, and each comment's
  box lies over the edited content on both sides.
- **Foxit check:** run the same pair in Foxit and save `foxit-compare.pdf`. Compare the page structure of
  both result documents (summary layout, legend, comment types).
- **Open:** how the Compare Table option differs from text comparison inside tables, and how Foxit
  reports a page that is both moved and edited. Black-box with two extra C3 variants.
