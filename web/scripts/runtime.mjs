// Puts everything the app needs to run Python on the device into public/runtime/: Pyodide, the wheels of the
// libraries pdfdesk uses there, and pdfdesk's own Python (commands, core, lang, fonts; not the Qt window).
// Nothing is loaded from the network when the app runs.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { zipSync } from "fflate";

const web = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out = path.join(web, "public", "runtime");
const cache = path.join(web, ".cache");
// PyMuPDF publishes a browser build for Pyodide 0.29 (ABI pyemscripten_2025_0); the two versions go together.
const WHEELS = [
  ["pymupdf", "1.28.2", "pyemscripten_2025_0_wasm32"],
  ["openpyxl", "3.1.5", "none-any"],          // Convert > To Excel
  ["et-xmlfile", "2.0.0", "none-any"],
];
const FROM_PYODIDE = ["lxml"];                   // the e-invoice XML (Invoice.Read, Invoice.Check)
const SKIP = new Set(["gui", "__pycache__", "instance.py", "cli.py"]);

async function wheel(name, version, tag) {
  const meta = await (await fetch(`https://pypi.org/pypi/${name}/${version}/json`)).json();
  const file = meta.urls.find((u) => u.filename.endsWith(tag + ".whl"));
  if (!file) throw new Error(`${name} ${version} has no ${tag} wheel`);
  const local = path.join(cache, file.filename);
  if (!fs.existsSync(local)) {
    console.log("downloading", file.filename);
    const data = Buffer.from(await (await fetch(file.url)).arrayBuffer());
    if (createHash("sha256").update(data).digest("hex") !== file.digests.sha256) throw new Error("bad checksum: " + file.filename);
    fs.writeFileSync(local, data);
  }
  fs.copyFileSync(local, path.join(out, "wheels", file.filename));
  return file.filename;
}

async function pyodidePackage(name) {
  const lock = JSON.parse(fs.readFileSync(path.join(web, "node_modules", "pyodide", "pyodide-lock.json"), "utf8"));
  const { version } = JSON.parse(fs.readFileSync(path.join(web, "node_modules", "pyodide", "package.json"), "utf8"));
  const pkg = lock.packages[name];
  const local = path.join(cache, pkg.file_name);
  if (!fs.existsSync(local)) {
    console.log("downloading", pkg.file_name);
    const url = `https://cdn.jsdelivr.net/pyodide/v${version}/full/${pkg.file_name}`;
    const data = Buffer.from(await (await fetch(url)).arrayBuffer());
    if (createHash("sha256").update(data).digest("hex") !== pkg.sha256) throw new Error("bad checksum: " + pkg.file_name);
    fs.writeFileSync(local, data);
  }
  fs.copyFileSync(local, path.join(out, "wheels", pkg.file_name));
  return pkg.file_name;
}

function sources(dir, prefix, files) {
  for (const name of fs.readdirSync(dir).sort()) {
    if (SKIP.has(name)) continue;
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) sources(full, prefix + name + "/", files);
    else files[prefix + name] = [fs.readFileSync(full), { level: name.endsWith(".py") || name.endsWith(".txt") ? 9 : 6 }];
  }
  return files;
}

fs.mkdirSync(path.join(out, "wheels"), { recursive: true });      // files are written over in place: a running dev server keeps serving them
fs.mkdirSync(path.join(out, "pyodide"), { recursive: true });
fs.mkdirSync(cache, { recursive: true });
const pyodide = path.join(web, "node_modules", "pyodide");
for (const f of ["pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"])
  fs.copyFileSync(path.join(pyodide, f), path.join(out, "pyodide", f));
const wheels = [];
for (const w of WHEELS) wheels.push(await wheel(...w));
for (const name of FROM_PYODIDE) wheels.push(await pyodidePackage(name));
for (const old of fs.readdirSync(path.join(out, "wheels"))) if (!wheels.includes(old)) fs.rmSync(path.join(out, "wheels", old));
fs.writeFileSync(path.join(out, "pdfdesk.zip"), zipSync(sources(path.join(web, "..", "pdfdesk"), "pdfdesk/", {})));
fs.copyFileSync(path.join(web, "..", "pdfdesk", "fonts", "GreatVibes-Regular.ttf"), path.join(out, "GreatVibes-Regular.ttf"));   // typed signatures
const version = JSON.parse(fs.readFileSync(path.join(web, "package.json"), "utf8")).version;
const desktop = /^version = "(.*)"/m.exec(fs.readFileSync(path.join(web, "..", "pyproject.toml"), "utf8"))[1];
if (desktop !== version) throw new Error(`web/package.json says version ${version}, pyproject.toml says ${desktop}: they are one product, set both`);
fs.writeFileSync(path.join(out, "runtime.json"), JSON.stringify({ version, wheels }));
const size = (dir) => fs.readdirSync(dir, { withFileTypes: true })
  .reduce((n, e) => n + (e.isDirectory() ? size(path.join(dir, e.name)) : fs.statSync(path.join(dir, e.name)).size), 0);
console.log(`runtime: ${(size(out) / 2 ** 20).toFixed(1)} MB in public/runtime`);
