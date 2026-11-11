// Runs the command tests on the Python the browser and phone builds use (Pyodide with the wheels in
// public/runtime), so a command that needs something missing there shows up here and not on a phone.
//   node scripts/pytest.mjs [pytest options]        (pytest itself is fetched from the Pyodide CDN)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const web = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const runtime = path.join(web, "public", "runtime");
const py = await loadPyodide();
py.FS.mkdirTree("/repo");
py.FS.mount(py.FS.filesystems.NODEFS, { root: path.join(web, "..") }, "/repo");
const quiet = { messageCallback() {} };
for (const w of JSON.parse(fs.readFileSync(path.join(runtime, "runtime.json"), "utf8")).wheels)
  await py.loadPackage(path.join(runtime, "wheels", w), quiet);
await py.loadPackage("pytest", quiet);
// what needs a library that has no build for the browser (pikepdf, pyHanko, pdf2docx, OCRmyPDF, PaddleOCR)
const DESKTOP_ONLY = ["save_after_snapshots_keeps_placed_signature", "digital_sign_validate_certify", "placed_signature_is_one_movable_object",
  "export_formats", "pdfa", "ocr_makes_scan_searchable", "auto_redact_text_and_scan"];
const args = [...DESKTOP_ONLY.map((t) => `--deselect=tests/test_commands.py::test_${t}`), ...process.argv.slice(2)];
const code = await py.runPythonAsync(`
import os, sys, pytest
sys.path[:0] = ["/repo", "/repo/tests"]
os.chdir("/repo")
int(pytest.main(["-q", "--no-header", "-p", "no:cacheprovider", "tests/test_webapi.py", "tests/test_commands.py", *${JSON.stringify(args)}]))
`);
process.exit(code);
