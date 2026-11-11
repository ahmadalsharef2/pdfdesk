// Runs pdfdesk's Python (pdfdesk/webapi.py) in Pyodide, off the main thread. One message in, one out:
//   { id, fn, args, files? }  ->  { id, ok, blob? }  or  { id, error, kind }
// files are written to the work folder first; an argument { $file: n } becomes the n-th file's path.
import { loadPyodide } from "pyodide";

type Request = { id: number; fn: string; args: unknown; files?: { name: string; data: ArrayBuffer }[] };
let call: ((fn: string, args: string) => { toJs(): [string, Uint8Array | undefined]; destroy(): void }) | null = null;
let fs: { mkdirTree(p: string): void; writeFile(p: string, d: Uint8Array): void } | null = null;
let uploads = 0;

async function boot(base: string) {
  const stage = (text: string) => postMessage({ stage: text });
  stage("python");
  const py = await loadPyodide({ indexURL: base + "pyodide/" });
  stage("libraries");
  const manifest = await (await fetch(base + "runtime.json")).json();
  await py.loadPackage(manifest.wheels.map((w: string) => base + "wheels/" + w), { messageCallback() {} });
  py.unpackArchive(await (await fetch(base + "pdfdesk.zip")).arrayBuffer(), "zip");
  stage("pdfdesk");
  call = py.pyimport("pdfdesk.webapi").call;
  fs = py.FS;
  postMessage({ ready: manifest.version });
}

function paths(value: unknown, files: string[]): unknown {
  if (Array.isArray(value)) return value.map((v) => paths(v, files));
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.$file === "number") return files[o.$file];
    return Object.fromEntries(Object.entries(o).map(([k, v]) => [k, paths(v, files)]));
  }
  return value;
}

onmessage = async (e: MessageEvent) => {
  if (e.data.boot) {
    try {
      await boot(e.data.boot);
    } catch (err) {
      postMessage({ failed: String(err) });
    }
    return;
  }
  const { id, fn, args, files } = e.data as Request;
  try {
    const stored = (files ?? []).map((f) => {
      const dir = `/tmp/in/${++uploads}`;
      fs!.mkdirTree(dir);
      const path = `${dir}/${f.name.replace(/[\/\\]/g, "_")}`;
      fs!.writeFile(path, new Uint8Array(f.data));
      return path;
    });
    const res = call!(fn, JSON.stringify(paths(args, stored)));
    const [json, blob] = res.toJs();
    res.destroy();
    const out = JSON.parse(json);
    if ("error" in out) postMessage({ id, error: out.error, kind: out.kind });
    else if (blob) postMessage({ id, ok: out.ok, blob: blob.buffer }, { transfer: [blob.buffer as ArrayBuffer] });
    else postMessage({ id, ok: out.ok });
  } catch (err) {
    postMessage({ id, error: String(err), kind: "Crash" });
  }
};
