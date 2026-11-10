# pdfdesk — end-to-end experience pass

Goal: every current feature feels smooth on every kind of document a user brings, the way a Foxit PhantomPDF
user expects it to. Not new features: the existing ones done right. Ahmad wants a working app, short reports and
few tests; everything is committed on main (no co-author trailer, fetch before push). Delete this file when the
pass is done; keep durable notes in HANDOFF.md.

## How to work

0. Downloaded test documents live in `tests/corpus/web/` (git-ignored): IRS W-9 and 1040 forms, a two-column
   arXiv paper, pdf.js samples (annotations, Arabic, Hebrew, CJK vertical, rotation). `tests/journeys.py` makes
   the rest (scanned, odd pages, images, protected) and drives them: `QT_QPA_PLATFORM=offscreen .venv/bin/python
   -u tests/journeys.py OUTDIR [journey …]`; lines starting with `!!` are problems.
1. Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -u tests/sweep_gui.py`. It opens a document, presses every
   ribbon action and every tool gesture with dialogs auto-answered, and prints `EXC` (crash), `BOX` (error or
   warning box) and `STDERR` lines. Fix every line it prints. Re-run until it prints `no problems found`.
2. For each journey below, write a short script (see `tests/sweep_gui.py` and the pattern in `tests/test_gui.py`
   for driving the window; `QT_QPA_PLATFORM=xcb` for the real display) that performs the journey and saves
   `w.grab()` screenshots after each step into the scratchpad. Look at the screenshots. Judge them against the
   criteria in "What smooth means". Write each finding as one line under "Findings" here, fix it, re-run the
   journey, then move the line to "Done".
3. Keep `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` green; add a test only when a fix needs one
   (tests/test_lang.py already fails when a new `tr()` string lacks German or Arabic).
4. Commit per group of related fixes with a message that names what a user gains.

## Documents to use

Make them in a script with PyMuPDF so journeys are repeatable:

- **Text contract** — `tests/conftest.py: make_contract` (6 pages, text, bookmarks).
- **Real manual** — `tests/corpus/foxit/manual.pdf` (446 pages, 658 bookmarks, images on most pages, mixed
  content). Use it for performance and for Edit Object / images / links.
- **Scanned page** — render the contract's first page to a 150 dpi image and wrap it in a PDF (`img2pdf` or
  `pymupdf` insert_image). No text layer: Select Text, Highlight, Find and Edit Text must tell the user to run
  OCR instead of silently doing nothing.
- **Form** — contract plus `Form.AddText`, `Form.AddCheckbox`, `Form.AddCombo` fields on page 1.
- **Protected** — contract saved with user and owner passwords (see `test_save_keeps_password`).
- **E-invoice** — made with `Invoice.Create`, so the Invoice tab has something to show.
- **Arabic** — a page with Arabic text (`insert_text` with a Unicode font from `core/fonts.py`), opened with the
  window in Arabic (`lang.install(app, "ar")`).
- **Odd pages** — a document with a rotated page, a landscape page and an A3 page among A4 pages.
- **Big** — the manual duplicated to ~2000 pages (`Pages.Combine` of itself), for opening, scrolling, zoom,
  thumbnails and memory (`DocView.CACHE_BYTES`, `relayout` reads every page).

## Journeys

Each journey lists steps, then what to look at. "Message" means the status bar text at the bottom left.

### Open and read
- Start page → Recent → open the manual. Look at: time to first paint, fit width applied once the window has its
  size, no horizontal scrollbar, thumbnails fill in without freezing scrolling, bookmark click lands on the page,
  page number in the status bar follows scrolling, Ctrl+wheel zooms about the mouse, PageDown/Home/End work,
  F4 toggles the panel and the view re-fits.
- Open five documents, switch tabs: each keeps its own zoom, scroll position, tool and selection; the title and
  status bar follow; Ctrl+W closes the current one and asks only when modified.
- Odd pages: fit width uses the widest page; a rotated page shows rotated and tools land on it (drag a rectangle
  on it, check the saved annotation's coordinates); Fit Page on the A3 page fits that page.
- Big: open under 3 s; zoom steps under 300 ms; memory stays bounded while scrolling 200 pages at 300 %.

### Select, find, copy
- Select tool drag across lines and across a column break; right-click → Copy, Highlight, Add Bookmark, Search
  the Web. Look at: selection follows reading order, stays visible after the menu, Escape clears it.
- Find box: Enter steps through hits, hits are highlighted on the page and the view scrolls to the first one, a
  miss says so in the message, Advanced Search over a folder lists hits and double-click opens the file at the page.
- Scanned page: Select, Highlight, Find and Edit Text say "no text layer — run OCR (Convert > OCR)" in the message
  instead of doing nothing.

### Comment tools (on the contract and on the manual)
For each of highlight, underline, strikeout, squiggly, replace text, area highlight, note, file, typewriter,
text box, callout, rectangle, oval, line, arrow, polygon, cloud, polyline, pencil, stamp:
- Draw one. Look at: a preview while dragging, the result appears where the mouse was (also at 50 % and 300 %
  zoom, also on the rotated page), the new comment is selected afterwards, the message names what was made,
  Ctrl+Z removes it and says what it undid, the Comments panel lists it, the tool stays active for the next one.
- Decide one rule and apply it everywhere: a comment tool stays active until Escape or Hand (Foxit's "keep tool
  selected"); Escape with nothing in progress returns to Hand.
- Typewriter, Add Text, Text box and Callout open a dialog for the text. Foxit types in place. Reuse
  `gui/text_editor.InlineTextEditor` so the user types on the page and Enter keeps it; keep the dialog only when
  the text would not fit on screen.
- Hand on a comment: move, resize at a corner (box comments only), double-click → properties, right-click →
  color, opacity, font size, line width, status, reply, copy, cut, delete. Drag onto another page. Look at: the
  cursor changes over handles and bodies, the drag preview is smooth, nothing jumps on release.
- Default colors: pick a color in the ribbon color button, draw, "Use as Default Color" from the menu, restart,
  the color is still there.

### Edit text and objects (manual, pages with images and headings)
- Edit Text: hover shows the line box, click opens the inline editor over the line with the same size and color,
  typing reflows that line, Enter keeps, Escape cancels, clicking elsewhere keeps. Change size and color. Look
  at: the editor sits on the line at every zoom and after a window resize, the page under it does not shift,
  undo restores the line exactly.
- Edit Object: click an image, drag it, resize at a corner (aspect kept), rotate and flip from the menu,
  Position & Size dialog in mm, Delete, Ctrl+C/Ctrl+V into the same page and into another document, Export as
  image. Same with a text block and a vector shape. Look at: the selection box matches the visible object, the
  object does not blur or shift after a transform, undo is one step per action.
- Add Text and Add Image: placed where clicked, selected afterwards, movable right away by Hand.

### Pages
- Thumbnails: drag to reorder (the view and the panel agree), multi-select then right-click Delete, Rotate,
  Extract, Duplicate, Insert blank, Insert from file. Organize tab: the same from the ribbon with page ranges.
  Look at: the current page is highlighted in the panel, the panel scrolls to it, undo restores order.

### Forms
- Form document: Hand clicks a field → fill dialog; right-click → Clear, Reset all, Delete. Form tab: add each
  field type by dragging, Recognize on the contract (lines of "Name: ____"), Export/Import data, Flatten.

### Protect, sign, redact
- Protected document: open with the owner password → everything works; open with the user password → tools
  refuse with one clear message, Save warns. Set/remove password, save, reopen.
- Sign: place a typed and an ink signature, move and resize, digitally sign with a created ID, validate.
- Redact: mark text, mark an area, Auto Redact with the e-mail pattern, Apply; the text is gone from
  `get_text()` and from the image of the page.

### Convert, invoice, language
- From File (docx, image), To Word / Excel / PowerPoint / images / text / PDF/A, Combine, OCR on the scanned page
  (the first run downloads models: the message must say so and the window must not freeze).
- Invoice tab: create, view, check, embed XML, save XML.
- German and Arabic: every label, hint, dialog and message is translated (tests/test_lang.py), Arabic layout
  is right-to-left including the ribbon, the page view and the status bar; numbers and file names read right.

## What smooth means (judge every screenshot against these)

- The result appears exactly where the user pointed, at any zoom, on any page rotation.
- Something is always selected or in focus after an action, so the next key or click does something sensible.
- The status bar always says what the tool does now and what just happened; never an empty bar after an action.
- No dialog where typing on the page would do; a dialog never asks for something the app already knows.
- Every change is one undo step with a label a user understands; undo and redo never leave a selection pointing
  at something that is gone.
- Nothing freezes: anything over half a second shows a message first (`Main._busy`), anything over three seconds
  runs in a thread with the window usable.
- Panels, title, tab text and the Comments list agree with the document after every change.
- Keyboard: Escape backs out of anything; Delete removes the selection; Ctrl+C/X/V, Ctrl+Z/Y, Ctrl+F, Ctrl+0,
  Ctrl++/-, PageUp/Down, Home/End all work with the page view focused.
- Right-click on anything offers the things a user would want for that thing, and nothing that cannot apply.
- The same action from the ribbon, the right-click menu, the keyboard and the Tell-me box behaves identically.

## Findings

(one line each: journey — what is wrong — where in the code)

## Done

Batch 1 (sweep + journeys, 2026-11-10):
- Replace and the "Find “…”" item of the text menu crashed: `tr()`'s own parameter was named `text`.
- Split crashed: the splitter widget was stored as `self.split`, hiding the Split command.
- Edit Object did not see shapes drawn by PyMuPDF and others (state operators between path and paint).
- New comments are selected after they are made; Add Text selects the added text.
- Arrow keys nudge the selection (Shift: 10 pt); quick nudges are one undo step.
- Typewriter and Add Text are typed on the page (Enter: new line; click elsewhere or Esc keeps it).
- Double-click: a word (Select), a typewriter comment's text, a text object (Edit Object) edits in place.
- Form fields are typed into on the page; Tab / Shift+Tab move between fields; status shows a readable name.
- Hand cursor shows what a click does (I-beam on text fields, pointer on check boxes, move on comments).
- Ctrl+A selects the page's text; Home / End / Space / Shift+Space navigate; Escape with nothing selected
  returns to Hand.
- Thumbnails follow the current page.
- Scanned pages: Select, Highlight, Edit Text and Find say to run OCR instead of doing nothing.
- The open editor follows scrolling and resizing instead of ending the edit; it hides the text it replaces.
- Page ranges accept spaces, en dashes and semicolons; a wrong range gets a clear message.
- Resizing a shape no longer forces its proportions (images and text keep them; Shift switches).
