import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";

const { version } = JSON.parse(fs.readFileSync(new URL("./package.json", import.meta.url), "utf8"));
const native = process.env.PDFDESK_TARGET === "native";       // the build that goes into the phone apps

// The browser may load nothing from anywhere else, so a document cannot leave the device even by mistake.
// The phone apps load their own files through the app's bridge and get no such header.
const POLICY = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "font-src 'self'; worker-src 'self' blob:; frame-src blob:; connect-src 'self'; form-action 'none'; base-uri 'self'";

function walk(dir: string, prefix = ""): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name), prefix + e.name + "/") : [prefix + e.name]));
}

/** Writes sw.js: every file of the build is kept by the browser, so the web app starts and works without a network. */
function offline(): Plugin {
  return {
    name: "pdfdesk-offline",
    apply: "build",
    transformIndexHtml: (html) => (native ? html : html.replace("<meta charset", `<meta http-equiv="Content-Security-Policy" content="${POLICY}" />\n    <meta charset`)),
    closeBundle() {
      const dist = path.resolve("dist");
      const files = walk(dist).filter((f) => f !== "sw.js").sort();
      const hash = createHash("sha256");
      for (const f of files) hash.update(f).update(fs.readFileSync(path.join(dist, f)));
      const list = JSON.stringify(["./", ...files.filter((f) => f !== "index.html")]);
      fs.writeFileSync(path.join(dist, "sw.js"), `// written by the build (vite.config.ts)
const CACHE = "pdfdesk-${hash.digest("hex").slice(0, 16)}";
const FILES = ${list};
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request)));
});
`);
    },
  };
}

// base "./": the same build is served from a web folder and from inside the phone apps.
export default defineConfig({
  base: "./",
  define: { __VERSION__: JSON.stringify(version) },
  build: { target: "es2022", chunkSizeWarningLimit: 2000 },
  worker: { format: "es" },
  optimizeDeps: { exclude: ["pyodide"] },
  plugins: [offline()],
});
