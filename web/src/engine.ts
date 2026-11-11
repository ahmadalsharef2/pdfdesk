// The app's side of the Python worker: call(fn, args) resolves with what pdfdesk/webapi.py returns.
export class EngineError extends Error {
  constructor(message: string, public kind: string) {
    super(message);
  }
}

export type Upload = { name: string; data: ArrayBuffer };
type Waiting = { resolve: (v: any) => void; reject: (e: Error) => void };

const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
const waiting = new Map<number, Waiting>();
let seq = 0;
let onStage: (stage: string) => void = () => {};

export const ready = new Promise<string>((resolve, reject) => {
  worker.onmessage = (e: MessageEvent) => {
    const m = e.data;
    if (m.stage) return onStage(m.stage);
    if (m.ready) return resolve(m.ready);
    if (m.failed) return reject(new Error(m.failed));
    const w = waiting.get(m.id);
    if (!w) return;
    waiting.delete(m.id);
    if ("error" in m) w.reject(new EngineError(m.error, m.kind));
    else w.resolve(m.blob ? { meta: m.ok, data: new Uint8Array(m.blob) } : m.ok);
  };
  worker.onerror = (e) => reject(new Error(e.message));
});

export function start(stage: (s: string) => void) {
  onStage = stage;
  worker.postMessage({ boot: new URL("runtime/", document.baseURI).href });
  return ready;
}

// Calls the person waits for show a spinner when they take long; what the view fetches on its own does not.
const QUIET = new Set(["render", "words", "page_items", "state", "info", "line_at", "strings", "activate", "available"]);
let slow = 0, timer = 0, shown = false;
let busyHook: (on: boolean) => void = () => {};
export const onBusy = (hook: (on: boolean) => void) => (busyHook = hook);

function track(fn: string, done: Promise<unknown>) {
  if (QUIET.has(fn)) return;
  if (++slow === 1) timer = window.setTimeout(() => busyHook((shown = true)), 450);
  done.catch(() => {}).finally(() => {
    if (--slow) return;
    clearTimeout(timer);
    if (shown) busyHook((shown = false));
  });
}

/** Argument that stands for an uploaded file: Python gets its path. */
export const file = (n: number) => ({ $file: n });

export async function call<T = any>(fn: string, args: object = {}, files: Upload[] = []): Promise<T> {
  await ready;
  const done = new Promise<T>((resolve, reject) => {
    const id = ++seq;
    waiting.set(id, { resolve, reject });
    worker.postMessage({ id, fn, args, files }, files.map((f) => f.data));
  });
  track(fn, done);
  return done;
}
