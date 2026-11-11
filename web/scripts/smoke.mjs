// The built app (dist/) in a real browser, at a desktop and a phone size: start, open a PDF, highlight a line,
// save, and read the saved file back. Run `npm run build` first.   PDFDESK_KEY=… node scripts/smoke.mjs
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, devices } from "playwright";

const dist = path.join(path.dirname(path.dirname(fileURLToPath(import.meta.url))), "dist");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".wasm": "application/wasm", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer((req, res) => {
  const file = path.join(dist, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!file.startsWith(dist) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream" }).end(fs.readFileSync(file));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const url = `http://127.0.0.1:${server.address().port}/`;

// a one-page PDF with one line of text; MuPDF rebuilds the missing cross-reference table
const stream = "BT /F1 24 Tf 72 700 Td (Hello pdfdesk) Tj ET";
const sample = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "pdfdesk-smoke-")), "hello.pdf");
fs.writeFileSync(sample, `%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n` +
  `3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n` +
  `4 0 obj<</Length ${stream.length}>>stream\n${stream}\nendstream endobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n`);

const KEY = process.env.PDFDESK_KEY;                    // the product key is not in the repository; without it only the start is checked
const browser = await chromium.launch();
let failed = false;
for (const [name, options] of [["desktop", { viewport: { width: 1200, height: 800 } }], ["phone", devices["Pixel 7"]]]) {
  const context = await browser.newContext({ ...options, acceptDownloads: true });
  const page = await context.newPage();
  await page.addInitScript(() => { delete window.showOpenFilePicker; delete window.showSaveFilePicker; });     // plain file inputs and downloads
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  try {
    await page.goto(url);
    await page.fill(".key-gate input", "wrong key", { timeout: 120_000 });          // shut until the product key is given
    await page.click(".key-gate .btn");
    await page.waitForFunction(() => document.querySelector(".key-wrong").textContent !== "");
    if (!KEY) {
      if (problems.length) throw new Error("errors in the page: " + problems.join(" | "));
      console.log(`${name}: starts and stays shut without the key (set PDFDESK_KEY to test the rest)`);
      continue;
    }
    await page.fill(".key-gate input", KEY);
    await page.click(".key-gate .btn");
    await page.waitForSelector(".start-actions", { timeout: 120_000 });
    await page.reload();                                                             // the key is remembered
    await page.waitForSelector(".start-actions", { timeout: 120_000 });
    const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.click(".start-actions .btn.primary")]);
    await chooser.setFiles(sample);
    await page.waitForSelector(".page canvas.bitmap", { timeout: 60_000 });
    await page.click('.tabs button:text-is("Comment")');
    await page.click('.strip .tool[data-tool="highlight"]');
    const box = await page.locator(".page").first().boundingBox();
    const at = (x, y) => [box.x + (x / 595) * box.width, box.y + (y / 842) * box.height];
    await page.mouse.move(...at(76, 136));
    await page.mouse.down();
    await page.mouse.move(...at(140, 137), { steps: 5 });
    await page.mouse.move(...at(205, 137), { steps: 5 });
    await page.mouse.up();
    await page.waitForFunction(() => !document.querySelector('.top .icon-btn[aria-label="Undo"]').disabled, null, { timeout: 30_000 });
    const [download] = await Promise.all([page.waitForEvent("download"), page.click('.top .icon-btn[aria-label="Save"]')]);
    const saved = fs.readFileSync(await download.path());
    if (!saved.subarray(0, 5).equals(Buffer.from("%PDF-")) || !saved.includes("/Highlight")) throw new Error("the saved file has no highlight");
    if (problems.length) throw new Error("errors in the page: " + problems.join(" | "));
    console.log(`${name}: ok (${saved.length} bytes saved)`);
  } catch (e) {
    failed = true;
    console.error(`${name}: FAILED: ${e.message}`);
  }
  await context.close();
}
await browser.close();
server.close();
process.exit(failed ? 1 : 0);
