# pdfdesk — handoff

A PDF editor that does what Foxit PhantomPDF Business 10 does, built on open-source libraries. The desktop
window runs on Linux, Windows and macOS; `web/` is the same commands in a browser and as Android and iOS apps.
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
- `tests/test_commands.py` (headless), `tests/test_gui.py` (offscreen window) and `tests/test_lang.py`, which fails
  when a `tr()` string has no German or Arabic entry, or a table keeps a string the interface no longer shows.

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
- PyMuPDF and Ghostscript are AGPL-3.0: fine for personal use, distribution needs the AGPL. A public web copy
  or a store app is distribution.
- Text, typewriter comments, images and signatures are placed as the page is seen: on a page with /Rotate (a
  sideways scan) the commands turn them so they stand upright.

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

- Editors on the page (`gui/text_editor.py`): `DocView._start_editor` opens one at a time; `_edit_target["kind"]`
  is "line" (Edit Text), "new" (Typewriter / Add Text), "annot" (a text comment's text) or "field" (form field,
  Tab moves on). `_commit_editor` turns it into one tool action. The editor follows scrolling and zoom changes.
- Tool actions that make a comment (`Main.COMMENT_ACTIONS`) select the new comment afterwards. Arrow-key nudges
  use their own undo labels ("Nudge …"), which `DocView.checkpoint` merges when they come within 0.8 s.
- `tests/sweep_gui.py` presses every ribbon action; `tests/journeys.py` drives user journeys with real events on
  many documents (downloaded ones in `tests/corpus/web/`, git-ignored). Both are run by hand, not by pytest.

## Browser and phone apps (`web/`)

Everything runs on the device; there is no server. The Python commands run unchanged in Pyodide (Python
compiled to WebAssembly) in a worker; `pdfdesk/webapi.py` is what the interface calls, `web/src/` is the interface
(TypeScript, no framework). The phone apps are the same build inside Capacitor (`web/android`, `web/ios`).

```
cd web && npm install
npm run dev                      # http://localhost:5173, Python and wheels are copied to public/runtime first
npm run build                    # dist/: static files for any web space, works offline after the first visit
npm run build:native             # the same without the browser security header, copied into android/ and ios/
node scripts/pytest.mjs          # the command tests on the browser's Python
node scripts/smoke.mjs           # dist/ in headless Chromium, desktop and phone size
../.venv/bin/python scripts/icons.py     # icons and launch screens again, after the app icon changes
```

- `web/src/`: `main.ts` starts Python, then loads `app.ts` (ribbon, tools, dialogs). `viewer.ts` is the page view
  and gestures; a gesture ends in an action that `app.ts` turns into a command, as `DocView.toolAction` and
  `Main.on_tool` do. `platform.ts` is everything that differs between browser and phone (open, save, share).
- Interface strings are the same tables (`pdfdesk/lang/`); `tests/test_lang.py` scans `web/src` too.
- PyMuPDF's only browser build is 1.28.2 for Pyodide 0.29 (the desktop has 2.0). Both versions are pinned in
  `web/package.json` and `web/scripts/runtime.mjs` and must change together.
- Left out there, because the library has no browser build: Edit Object (pikepdf), OCR and Auto Redact on scans
  (PaddleOCR), digital signatures (pyHanko), To Word, PDF/A and creating e-invoices. `webapi.available()` lists
  what a build can do and the ribbon hides the rest. `pdfdesk/fonts/` holds the fonts those builds (and macOS,
  Windows) use when the system has none.
- A browser build carries a Content-Security-Policy that forbids every outside address, so a document cannot
  leave the device; the phone build has none because the app's own bridge would be blocked.
- Vite's dev server lists `public/` once at start: if `public/runtime` is deleted and made again while it runs,
  it serves the start page for those files and Python fails to load. `runtime.mjs` writes in place for that reason.
- The version is in `pyproject.toml` and `web/package.json` (`runtime.mjs` stops when they differ); the Android
  and iOS versions are read from the latter.
- App ID `io.github.ahmadalsharef2.pdfdesk` (Capacitor config, Android, iOS, the macOS bundle). It cannot change
  once an app is in a store.
- Seen working: the browser build in Chromium at desktop and phone size with touch (journeys with screenshots,
  offline start), and the Android .apk builds (debug, and release signed from the `ANDROID_*` variables).
  Never run so far: the .apk on a phone, the iOS build, the macOS build. Their jobs are in the release
  workflow and do not hold a release back when they fail.

## Not built yet

XFA and form JavaScript, Action Wizard (`.sequ`), veraPDF validation, accessibility, read aloud, portfolios,
scanner input, shared review, cloud connectors, redaction code sets. Share, Connect and Accessibility tabs
are placeholders. Foxit's code, stamps and assets are never copied; its licence files are never touched.

## Foxit reference install

Wine bundle `~/Apps/FoxitPhantomPDF/` (repair with its `install.sh`), Business 10.0.0.35798. Its 446-page
manual can be copied to `tests/corpus/foxit/manual.pdf` (git-ignored). REA 6.7.0 and Ghidra 12.1.4 are set
up for behaviour questions only: `source ~/.nvm/nvm.sh && nvm use 22.20.0 && export
GHIDRA_INSTALL_DIR="$HOME/Apps/ghidra_12.1.4_PUBLIC"`, then `npx -y rea-agents@6.7.0 doctor`.

## Product key

Every edition stays shut until the product key was entered once (`pdfdesk/core/license.py`). For now there is one
hardcoded key for everyone; the code holds only its SHA-256 and the key is not in the repository (the tests swap in their own; the
browser test takes it from `PDFDESK_KEY`, a repository secret in CI). The
desktop window asks in `launch()` and keeps the key in the settings, `pdfdesk run` reads the settings or
`PDFDESK_KEY`, the browser and phone apps ask on the start screen (`web/src/main.ts`) and the bridge refuses every
call before `activate`. This is a gate, not protection: while PyMuPDF (AGPL) is the engine, the source has to be
given to whoever gets the app, and the check can be taken out.
