// Getting files in and out: a browser downloads or writes through its file pickers; the phone apps save into
// the app's Documents folder and hand files to other apps through the share sheet.
import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { Directory, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { tr } from "./i18n";

export const native = Capacitor.isNativePlatform();
export const FOLDER = "pdfdesk";
export type Picked = { name: string; data: ArrayBuffer; handle?: FileSystemFileHandle };
export const PDF = { description: "PDF", accept: { "application/pdf": [".pdf"] } };
export const IMPORTABLE = ".pdf,.png,.jpg,.jpeg,.gif,.bmp,.tif,.tiff,.webp,.txt,.html,.htm,.xml,.svg,.epub,.xps,.cbz";

const picker = () => (window as any).showOpenFilePicker as undefined | ((o: object) => Promise<FileSystemFileHandle[]>);

/** Let the person choose files. Browsers with file handles give one, so Save can write back to the file. */
export async function pick(accept: string, multiple = false): Promise<Picked[]> {
  if (!native && picker() && accept === ".pdf" && !multiple) {
    try {
      const [handle] = await picker()!({ types: [PDF] });
      const f = await handle.getFile();
      return [{ name: f.name, data: await f.arrayBuffer(), handle }];
    } catch {
      return [];                                 // closed without choosing
    }
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.multiple = multiple;
    input.onchange = async () => resolve(await Promise.all([...(input.files ?? [])].map(async (f) => ({ name: f.name, data: await f.arrayBuffer() }))));
    input.oncancel = () => resolve([]);
    input.click();
  });
}

function base64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

function bytes(b64: string): ArrayBuffer {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out.buffer;
}

/** Write a file in pieces: the bridge to the phone's file system takes text, and one huge string stalls it. */
async function write(path: string, directory: Directory, data: Uint8Array): Promise<string> {
  const step = 3 * 256 * 1024;
  const first = await Filesystem.writeFile({ path, directory, data: base64(data.subarray(0, step)), recursive: true });
  for (let i = step; i < data.length; i += step) await Filesystem.appendFile({ path, directory, data: base64(data.subarray(i, i + step)) });
  return first.uri;
}

function download(name: string, data: Uint8Array, mime: string) {
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Save a file where the person will find it. Returns what to tell them, and the handle it now writes to. */
export async function save(name: string, data: Uint8Array, mime: string, handle?: FileSystemFileHandle, ask = false): Promise<{ message: string; handle?: FileSystemFileHandle } | null> {
  if (native) {
    try {
      await write(`${FOLDER}/${name}`, Directory.Documents, data);
      return { message: tr("Saved in {path}", { path: `Documents/${FOLDER}/${name}` }) };
    } catch {
      await share(name, data, mime);             // no access to Documents: let the person pick a place
      return { message: "" };
    }
  }
  const saver = (window as any).showSaveFilePicker as undefined | ((o: object) => Promise<FileSystemFileHandle>);
  if ((!handle || ask) && saver && mime === "application/pdf") {
    try {
      handle = await saver({ suggestedName: name, types: [PDF] });
    } catch {
      return null;
    }
  }
  if (handle && mime === "application/pdf") {
    const w = await (handle as any).createWritable();
    await w.write(data);
    await w.close();
    return { message: tr("Saved {path}", { path: handle.name }), handle };
  }
  download(name, data, mime);
  return { message: tr("Saved {path}", { path: name }) };
}

export const canShare = native || typeof navigator.canShare === "function";

export async function share(name: string, data: Uint8Array, mime: string) {
  if (native) {
    const uri = await write(name, Directory.Cache, data);
    await Share.share({ title: name, files: [uri] }).catch(() => {});      // closing the sheet is not an error
    return;
  }
  const f = new File([data as BlobPart], name, { type: mime });
  if (navigator.canShare?.({ files: [f] })) await navigator.share({ files: [f], title: name }).catch(() => {});
  else download(name, data, mime);
}

export async function print(data: Uint8Array) {
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type: "application/pdf" }));
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;width:0;height:0;border:0";
  frame.src = url;
  frame.onload = () => frame.contentWindow?.print();
  document.body.append(frame);
  setTimeout(() => { frame.remove(); URL.revokeObjectURL(url); }, 10 * 60_000);
}

/** Files saved by the phone app earlier, newest first. */
export async function recent(): Promise<{ name: string; time: number }[]> {
  if (!native) return [];
  try {
    const dir = await Filesystem.readdir({ path: FOLDER, directory: Directory.Documents });
    return dir.files.filter((f) => f.type === "file" && f.name.toLowerCase().endsWith(".pdf"))
      .map((f) => ({ name: f.name, time: f.mtime })).sort((a, b) => b.time - a.time).slice(0, 12);
  } catch {
    return [];
  }
}

export async function readRecent(name: string): Promise<Picked> {
  const f = await Filesystem.readFile({ path: `${FOLDER}/${name}`, directory: Directory.Documents });
  return { name, data: bytes(f.data as string) };
}

/** Files another app (or the system's "Open with") hands to pdfdesk. */
export function onIncoming(open: (f: Picked) => void) {
  const take = async (url?: string) => {
    if (!url || !/^(file|content):/.test(url)) return;
    try {
      const f = await Filesystem.readFile({ path: url });
      const name = decodeURIComponent(url.split(/[\/:]/).pop() || "document.pdf");
      open({ name: /\.\w{2,5}$/.test(name) ? name : name + ".pdf", data: bytes(f.data as string) });
    } catch (e) {
      console.error(e);
    }
  };
  if (native) {
    App.addListener("appUrlOpen", (e) => take(e.url));
    App.getLaunchUrl().then((r) => take(r?.url));
  }
  const queue = (window as any).launchQueue;      // an installed web app opened with a file
  queue?.setConsumer(async (params: { files: FileSystemFileHandle[] }) => {
    for (const handle of params.files) {
      const f = await handle.getFile();
      open({ name: f.name, data: await f.arrayBuffer(), handle });
    }
  });
}

export function openExternal(url: string) {
  window.open(url, "_blank", "noopener");
}
