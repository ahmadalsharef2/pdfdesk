# pdfdesk — handoff

A Linux PDF editor that does what Foxit PhantomPDF Business 10 does, built on open-source libraries.
Ahmad wants a working app, not documents: build, show it runs, keep reports short, no planning files,
few tests.

## Run

```
.venv/bin/python -m pdfdesk.cli [file.pdf]                         # window
.venv/bin/python -m pdfdesk.cli run <Command> in.pdf -o out.pdf --key value
.venv/bin/python -m pdfdesk.cli commands                            # list commands
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q            # tests
```

## Layout

- `pdfdesk/commands/`: every feature is a named command (`@command("Redact.Find")`). GUI, CLI and tests
  call the same commands.
- `pdfdesk/gui/`: Qt window. `app.py` main window and ribbon, `viewer.py` page view and mouse tools,
  `dialogs.py`, `invoice.py`, `theme.py` (the red accent; every colour derives from it).
- `pdfdesk/lang/`: `tr("English text")`; `de.py` and `ar.py` map English to German and Arabic. A missing
  key shows English. File > Language switches and restarts; Arabic turns the whole window right-to-left.
- `tests/test_commands.py` (headless) and `tests/test_gui.py` (offscreen window).

## Notes that are not obvious from the code

- Right-click menus: `pdfdesk --combine|--convert files…`. Linux: `packaging/linux/` (Nautilus extension, Nemo
  actions, Dolphin service menu), installed by the .deb. Windows: `packaging/pdfdesk.iss` registry entries.
  Explorer starts one process per file; `instance.py` lets one win a lock file and show the window, the rest hand
  their files over, and the window waits `Main.BATCH_MS` for stragglers before showing one Combine dialog.
  The Windows hand-over (named pipe) has not been run on Windows yet.

- PyMuPDF 2.0 drops encryption on a full save; `core/security.py` keeps the passwords and re-applies them.
- PyMuPDF unbinds an annotation once its page object is collected, so commands hold the page in a variable.
- OCR is PaddleOCR (`commands/ocr.py`), pinned to paddlepaddle 3.2.2: 3.3's oneDNN kernels fail on the models,
  and with oneDNN off a page takes ~45 s and huge memory. Models download to `~/.paddlex` on first use.
- Auto Redact (`Redact.Find`) reads scanned pages with Paddle and blanks the pixels under each mark. With Arabic
  plus Latin languages it reads with both models, because the Arabic one garbles e-mail addresses.
  In right-to-left lines the text layer stores digit runs in visual order; `protect._logical` turns them back.
- OCRmyPDF is used only for PDF/A; `convert._ocrmypdf_without_tesseract` skips its check for the tesseract program.
- PyMuPDF and Ghostscript are AGPL-3.0: fine for personal use, distribution needs the AGPL.

- Window and page sizes: `DocView.fit_mode` keeps Fit Width / Fit Page through resizes and maximizing
  (`resizeEvent` re-fits; `fit_zoom` measures the viewport without scrollbars, so the zoom does not depend on
  which bars happen to show). `set_zoom` keeps the point under the mouse (or the view centre) in place. Pages
  render at the screen's device pixel ratio. Windows size through `dialogs.size_for_screen` (never larger than
  the screen); the main window remembers its geometry in the settings (`window/geometry`). The status label has
  an Ignored width policy: a QLabel's minimum size is its whole text, which once forced a 1800 px wide window.

- Selection is one model in `gui/viewer.py`: a comment (`selected`) or a page object (`obj_sel`). The Hand tool
  also picks up what pdfdesk added (text, images, signatures, pastes), never the page's own art: add commands
  run inside `objects.adding()`, which wraps new content in `/PdfDesk BMC … EMC`; `Object.List` reports it as
  `added`. Dragging a selection onto another page moves it (`Comment.Transfer`, `Object.Transfer`).
- Copy / cut / paste (`gui/clipboard.py`): a JSON item under `application/x-pdfdesk-item`, plus text or an image
  for other programs. In its own document an object is duplicated instruction by instruction with its resources
  (`Object.Copy` / `Object.Paste`); into another document it goes as a one-page snapshot clipped to its box
  (`Object.PasteFrom`). Comments copy by object source (`Comment.Copy` / `Comment.Paste`). `Comment.Move`
  shifts /L, /Vertices, /InkList, /QuadPoints and /CL as well, because MuPDF refuses `set_rect` on lines.
- Typewriter and Add Text ask for size (default 10 pt, remembered per tool) and color; the Edit Text editor
  (`gui/text_editor.py`) has both; text objects have a Font size submenu (`Object.FontSize`). Settings go
  through `gui/prefs.py`. `Main.on_tool` is a table of handlers grouped by feature (`_build_handlers`).

## Not built yet

XFA and form JavaScript, Action Wizard (`.sequ`), veraPDF validation, accessibility, read aloud, portfolios,
scanner input, shared review, cloud connectors, redaction code sets. Share, Connect and Accessibility tabs
are placeholders. Foxit's code, stamps and assets are never copied; its licence files are never touched.

## Foxit reference install

Wine bundle `~/Apps/FoxitPhantomPDF/` (repair with its `install.sh`), Business 10.0.0.35798. Its 446-page
manual can be copied to `tests/corpus/foxit/manual.pdf` (git-ignored). REA 6.7.0 and Ghidra 12.1.4 are set
up for behaviour questions only: `source ~/.nvm/nvm.sh && nvm use 22.20.0 && export
GHIDRA_INSTALL_DIR="$HOME/Apps/ghidra_12.1.4_PUBLIC"`, then `npx -y rea-agents@6.7.0 doctor`.
