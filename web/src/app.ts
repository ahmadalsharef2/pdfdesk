// The window around the page view, in the browser and on phones. Tools and menu entries end in the same
// named commands the desktop app runs (pdfdesk/commands), through pdfdesk/webapi.py.
import { App } from "@capacitor/app";
import { SystemBars, SystemBarsStyle, SystemBarType } from "@capacitor/core";
import { Doc, type Comment, type FormField, type Rect } from "./doc";
import { busy, button, choose, chooseColor, confirm, form, h, hex, iconButton, prompt, rgb, sheet, toast } from "./dom";
import { call, EngineError, file, onBusy, type Upload } from "./engine";
import { LANGUAGES, language, setLanguage, tr } from "./i18n";
import { icon } from "./icons";
import * as pagesSheet from "./pages";
import * as platform from "./platform";
import * as signature from "./signature";
import { LINE_TOOLS, MARKUP_TOOLS, RECT_TOOLS, Viewer, type Action } from "./viewer";

type Tool = { key: string; label: string; icon: string; tool?: boolean; run?: () => unknown; needs?: string; always?: boolean };
declare const __VERSION__: string;

const viewer = new Viewer();
let doc: Doc | null = null;
let commands = new Set<string>();
let tab = "Home";
let sign: signature.Signature | null = null;
let stampName = "Approved";
let placing: { name: string; data: ArrayBuffer; ratio: number } | null = null;      // the image the Add Image tool places

// ---- settings kept on the device ----------------------------------------------------------------------
const DEFAULT_COLORS: Record<string, string> = {
  highlight: "#ffd900", "area-highlight": "#ffd900", underline: "#009900", strikeout: "#e61a1a", squiggly: "#1a4de6", note: "#ffd900",
  typewriter: "#000000", "add-text": "#000000",
};
const store = {
  get<T>(key: string, fallback: T): T {
    try {
      return JSON.parse(localStorage.getItem("pdfdesk." + key) ?? "null") ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem("pdfdesk." + key, JSON.stringify(value));
    } catch { /* private mode */ }
  },
};
const colors: Record<string, string> = store.get("colors", {});
const colorOf = (tool: string) => colors[tool] ?? DEFAULT_COLORS[tool] ?? "#e61a1a";
const fontSize = () => store.get("fontsize", 12);
const author = () => store.get<string | null>("author", null) || undefined;
viewer.style = (tool) => ({ color: colorOf(tool), width: 1.5 });

// ---- shell ---------------------------------------------------------------------------------------------
const title = h("h1", { class: "title" }, "pdfdesk");
const undoBtn = iconButton("undo", tr("Undo"), () => act(() => undo(false)));
const redoBtn = iconButton("redo", tr("Redo"), () => act(() => undo(true)));
const findBtn = iconButton("search", tr("Find"), () => toggleFind());
const saveBtn = iconButton(platform.native ? "share" : "save", platform.native ? tr("Share") : tr("Save"), () => act(() => (platform.native ? share() : save())));
const top = h("header", { class: "top" }, iconButton("menu", tr("File"), () => fileMenu()), title, undoBtn, redoBtn, findBtn, saveBtn);
const tabs = h("nav", { class: "tabs", role: "tablist" });
const strip = h("div", { class: "strip", role: "toolbar" });
const findInput = h("input", { type: "search", placeholder: tr("Find"), enterKeyHint: "search", "aria-label": tr("Find") });
const findCount = h("span", { class: "find-count" });
const findBar = h("div", { class: "findbar", hidden: true }, findInput, findCount,
  iconButton("up", tr("Previous match"), () => stepHit(-1)), iconButton("down", tr("Next match"), () => stepHit(1)),
  iconButton("close", tr("Close"), () => toggleFind(false)));
const stage = h("main", { class: "stage" });
const pageLabel = h("button", { type: "button", class: "page-label", title: tr("Go to"), onclick: () => act(gotoPage) });
const zoomLabel = h("button", { type: "button", class: "zoom-label", title: tr("Fit Width"), onclick: () => viewer.fitWidth() });
const status = h("footer", { class: "status" },
  iconButton("prev", tr("Previous page"), () => viewer.goto(viewer.currentPage() - 1)), pageLabel,
  iconButton("next", tr("Next page"), () => viewer.goto(viewer.currentPage() + 1)), h("span", { class: "grow" }),
  iconButton("zoom-out", tr("Zoom out"), () => viewer.setZoom(viewer.zoom / 1.25)), zoomLabel,
  iconButton("zoom-in", tr("Zoom in"), () => viewer.setZoom(viewer.zoom * 1.25)));
document.getElementById("app")!.append(top, h("div", { class: "ribbon" }, tabs, strip), findBar, h("div", { class: "work" }, stage, status));

function ribbonTabs(): Record<string, Tool[]> {
  const T = (key: string, label: string, needs?: string): Tool => ({ key, label, icon: key, tool: true, needs });
  const A = (key: string, label: string, run: () => unknown, needs?: string): Tool => ({ key, label, icon: key, run, needs });
  return {
    Home: [T("hand", tr("Hand")), T("select", tr("Select Text")), A("search", tr("Find"), () => toggleFind(true)), A("pages", tr("Pages"), openPages),
      A("bookmarks", tr("Bookmarks"), showBookmarks), A("comments", tr("Comments"), showComments),
      A("fit-width", tr("Fit Width"), () => viewer.fitWidth()), A("fit-page", tr("Fit Page"), () => viewer.fitPage())],
    Comment: [T("highlight", tr("Highlight")), T("underline", tr("Underline")), T("strikeout", tr("Strikeout")), T("squiggly", tr("Squiggly")),
      T("note", tr("Note")), T("typewriter", tr("Typewriter")), T("textbox", tr("Textbox")), T("pencil", tr("Pencil")),
      T("rectangle", tr("Rectangle")), T("oval", tr("Oval")), T("line", tr("Line")), T("arrow", tr("Arrow")),
      T("area-highlight", tr("Area Highlight")), A("stamp", tr("Stamp"), pickStamp), A("color", tr("Color"), pickColor)],
    "Fill & Sign": [T("add-text", tr("Add Text")), A("sign", tr("Sign"), startSigning), A("image", tr("Add Image"), startImage),
      A("flatten", tr("Flatten Form"), () => simple("Form.Flatten", tr("Flatten form"))), A("reset", tr("Reset Form"), () => simple("Form.Reset", tr("Reset form")))],
    Edit: [T("edit-text", tr("Edit Text")), T("add-text", tr("Add Text")), A("image", tr("Add Image"), startImage),
      A("replace", tr("Replace Text"), replaceText), A("link", tr("Create links"), detectLinks)],
    Organize: [A("pages", tr("Pages"), openPages), A("rotate-l", tr("Rotate Left"), () => rotatePages(-90)), A("rotate-r", tr("Rotate Right"), () => rotatePages(90)),
      A("delete", tr("Delete"), deletePages), A("extract", tr("Extract"), () => extractPages()), A("insert", tr("Insert Blank"), () => insertBlank(viewer.currentPage() + 1)),
      A("insert-file", tr("Insert File"), () => insertFile(viewer.currentPage() + 1)), A("reverse", tr("Reverse"), () => simple("Pages.Reverse", tr("Reverse pages"))),
      A("split", tr("Split"), splitDoc), A("crop", tr("Crop White"), cropWhite), A("header", tr("Header & Footer"), headerFooter),
      A("watermark", tr("Watermark"), watermark), A("background", tr("Background"), background)],
    Protect: [T("redact", tr("Mark for Redaction")), T("whiteout", tr("Whiteout")), A("search-redact", tr("Search & Redact"), searchRedact),
      A("apply", tr("Apply Redactions"), applyRedactions), A("password", tr("Password Protect"), passwordProtect),
      A("unlock", tr("Remove Security"), removeSecurity), A("hidden", tr("Remove Hidden Info"), removeHidden)],
    Convert: [{ ...A("create", tr("Create PDF"), () => createPdf(false)), always: true }, { ...A("combine", tr("Combine Files"), () => createPdf(true)), always: true },
      A("image", tr("To Image"), () => exportAs("image")), A("text", tr("To Text"), () => exportAs("text")), A("html", tr("To HTML"), () => exportAs("html")),
      A("excel", tr("To Excel"), () => exportAs("excel"), "Convert.ToExcel"), A("optimize", tr("Reduce File Size"), reduceSize)],
  };
}

function buildRibbon() {
  const all = ribbonTabs();
  tabs.replaceChildren(...Object.keys(all).map((name) =>
    h("button", { type: "button", role: "tab", class: name === tab ? "on" : "", "aria-selected": String(name === tab), onclick: () => { tab = name; buildRibbon(); } }, tr(name))));
  strip.replaceChildren(...all[tab].filter((t) => !t.needs || commands.has(t.needs)).map((t) => {
    const b = h("button", { type: "button", class: "tool" + (t.tool && viewer.tool === t.key ? " on" : ""), disabled: !doc && !t.always,
      onclick: () => (t.tool ? setTool(viewer.tool === t.key && t.key !== "hand" ? "hand" : t.key) : act(async () => { await t.run!(); })) },
      icon(t.icon), h("span", null, t.label));
    if (t.tool) b.dataset.tool = t.key;
    return b;
  }));
  strip.scrollLeft = 0;
  tabs.querySelector(".on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

const HINTS: Record<string, string> = {
  highlight: "Highlight: drag across text", underline: "Underline: drag across text", strikeout: "Strikeout: drag across text",
  squiggly: "Squiggly: drag across text", rectangle: "Rectangle: drag", oval: "Oval: drag", line: "Line: drag", arrow: "Arrow: drag",
  "area-highlight": "Area highlight: drag", whiteout: "Whiteout: drag over what to erase", stamp: "Stamp: drag a box", image: "Add image: drag a box",
};

function setTool(tool: string) {
  viewer.setTool(tool);
  for (const b of strip.querySelectorAll<HTMLElement>(".tool[data-tool]")) b.classList.toggle("on", b.dataset.tool === tool);
  if (HINTS[tool]) toast(tr(HINTS[tool]));
}

function refresh() {
  title.textContent = doc ? (doc.modified ? "● " : "") + doc.name : "pdfdesk";
  document.title = doc ? `${doc.name} — pdfdesk` : "pdfdesk";
  undoBtn.disabled = !doc?.undoLabel;
  redoBtn.disabled = !doc?.redoLabel;
  undoBtn.title = doc?.undoLabel ? `${tr("Undo")}: ${doc.undoLabel}` : tr("Undo");
  redoBtn.title = doc?.redoLabel ? `${tr("Redo")}: ${doc.redoLabel}` : tr("Redo");
  findBtn.disabled = saveBtn.disabled = !doc;
  status.hidden = !doc;
  showPage();
}

function showPage() {
  if (!doc) return;
  pageLabel.textContent = `${viewer.currentPage() + 1} / ${doc.pages.length}`;
  zoomLabel.textContent = `${Math.round(viewer.zoom * 100)}%`;
}

/** Run something the person asked for; what goes wrong is shown, not thrown. */
async function act(fn: () => unknown) {
  try {
    await fn();
  } catch (e) {
    console.error(e);
    toast(e instanceof EngineError ? e.message : String((e as Error)?.message ?? e), true);
  }
}

let stopBusy: (() => void) | null = null;
onBusy((on) => {
  stopBusy?.();
  stopBusy = on ? busy(tr("Working…")) : null;
});

// ---- opening and saving --------------------------------------------------------------------------------
async function setDoc(info: any, handle?: FileSystemFileHandle) {
  const old = doc;
  doc = new Doc(info);
  doc.handle = handle;
  doc.onchange = (pagesChanged) => {
    viewer.changed(pagesChanged);
    refresh();
  };
  stage.replaceChildren(viewer.el);
  viewer.setDoc(doc);
  setTool("hand");
  toggleFind(false);
  buildRibbon();
  refresh();
  if (old) await call("close", { sid: old.id });
  if (doc.readonly) toast(tr("This file was opened with its user password and does not allow changes. You can read and print it but not edit it."));
}

async function leaveOk(): Promise<boolean> {
  return !doc?.modified || confirm(tr("Close"), tr("{name} has changes that are not saved. They are lost if you go on.", { name: doc.name }), tr("Discard changes"), true);
}

async function openFile(f: platform.Picked) {
  if (!(await leaveOk())) return;
  let password: string | undefined;
  for (;;) {
    try {
      // the worker takes the bytes with it, so each try sends its own copy
      return await setDoc(await call("open_file", { path: file(0), name: f.name, password }, [{ name: f.name, data: f.data.slice(0) }]), f.handle);
    } catch (e) {
      if (!(e instanceof EngineError) || e.kind !== "NeedsPassword") throw e;
      if (password !== undefined) toast(tr("That password is not correct."), true);
      const typed = await prompt(tr("Password"), tr("Password for {name}:", { name: f.name }), "", "password");
      if (typed === null) return;
      password = typed;
    }
  }
}

async function openDialog() {
  const [f] = await platform.pick(".pdf");
  if (f) await openFile(f);
}

async function createPdf(several: boolean) {
  const files = await platform.pick(platform.IMPORTABLE, several);
  if (!files.length) return;
  if (files.length === 1) return openFile(files[0]);
  if (!(await leaveOk())) return;
  const uploads: Upload[] = files.map((f) => ({ name: f.name, data: f.data }));
  await setDoc(await call("create", { paths: files.map((_f, i) => file(i)), name: tr("untitled") + ".pdf" }, uploads));
}

/** The document as a file, asking for a password it needs to stay protected. */
async function bytes(): Promise<{ name: string; data: Uint8Array } | null> {
  if (!doc) return null;
  viewer.closeEditor(true);
  viewer.flushInk();
  const args: Record<string, unknown> = { sid: doc.id };
  for (;;) {
    const { meta, data } = await call("save", args);
    if (!meta.need) {
      await doc.refresh();
      return { name: meta.name, data };
    }
    const open = meta.need === "open";
    const pw = await prompt(open ? tr("Open password") : tr("Permissions password"),
      open ? tr("Enter the document's open password to keep it protected (leave empty for none):") : tr("Enter the permissions password to keep it protected:"), "", "password");
    if (pw === null || (!open && !pw)) return null;
    args[open ? "user_pw" : "owner_pw"] = pw;
  }
}

async function save(ask = false) {
  const out = await bytes();
  if (!out || !doc) return;
  const res = await platform.save(out.name, out.data, "application/pdf", doc.handle, ask);
  if (!res) return;
  doc.handle = res.handle ?? doc.handle;
  if (res.message) toast(res.message);
}

async function saveAs() {
  if (!doc) return;
  const name = await prompt(tr("Save As"), tr("Name:"), doc.name);
  if (!name?.trim()) return;
  await call("rename", { sid: doc.id, name: name.trim() });
  doc.handle = undefined;
  await save(true);
}

async function share() {
  const out = await bytes();
  if (out) await platform.share(out.name, out.data, "application/pdf");
}

async function printDoc() {
  if (!doc) return;
  const { data } = await call("copy", { sid: doc.id });
  await platform.print(data);
}

async function closeDoc() {
  if (!doc || !(await leaveOk())) return;
  const old = doc;
  doc = null;
  viewer.setDoc(null);
  await call("close", { sid: old.id });
  await showStart();
  buildRibbon();
  refresh();
}

async function undo(redo: boolean) {
  if (!doc) return;
  const label = await doc.undo(redo);
  if (label) toast(tr(redo ? "Redid: {what}" : "Undid: {what}", { what: label }));
}

function fileMenu() {
  const items: { key: string; label: string; icon: string }[] = [{ key: "open", label: tr("Open"), icon: "open" }];
  if (doc) {
    items.push({ key: "save", label: tr("Save"), icon: "save" }, { key: "saveas", label: tr("Save As…"), icon: "save" });
    if (platform.canShare) items.push({ key: "share", label: tr("Share"), icon: "share" });
    if (!platform.native) items.push({ key: "print", label: tr("Print"), icon: "print" });
    items.push({ key: "close", label: tr("Close"), icon: "close" });
  }
  items.push({ key: "language", label: tr("Language"), icon: "language" }, { key: "about", label: tr("About"), icon: "about" });
  choose(tr("File"), items).then((k) => act(async () => {
    if (k === "open") await openDialog();
    else if (k === "save") await save();
    else if (k === "saveas") await saveAs();
    else if (k === "share") await share();
    else if (k === "print") await printDoc();
    else if (k === "close") await closeDoc();
    else if (k === "language") await chooseLanguage();
    else if (k === "about") about();
  }));
}

async function chooseLanguage() {
  const code = await choose(tr("Language"), LANGUAGES.map(([key, label]) => ({ key, label: label + (key === language() ? " ✓" : "") })));
  if (!code || code === language() || !(await leaveOk())) return;
  await setLanguage(code);
  if (doc) doc.modified = false;                   // already asked; the page asks again when leaving otherwise
  location.reload();                               // every label is built again in the new language
}

function about() {
  sheet(tr("About"), [h("p", null, tr("pdfdesk {version} — a PDF editor that works on this device: your files are not sent anywhere.", { version: __VERSION__ })),
    h("p", { class: "hint" }, tr("Built on PyMuPDF (AGPL-3.0) and Pyodide. The source code is available under the same licence."))]);
}

// ---- start screen --------------------------------------------------------------------------------------
async function showStart() {
  const recent = await platform.recent();
  stage.replaceChildren(h("div", { class: "start" },
    h("div", { class: "start-head" }, h("h2", null, "pdfdesk"), h("p", null, tr("Read, mark up, sign and organize PDF files. Everything stays on this device."))),
    h("div", { class: "start-actions" },
      button(tr("Open"), () => act(openDialog), { icon: "open", primary: true }),
      button(tr("Create PDF"), () => act(() => createPdf(false)), { icon: "create" }),
      button(tr("Combine Files"), () => act(() => createPdf(true)), { icon: "combine" })),
    recent.length ? h("div", { class: "recent" }, h("h3", null, tr("Recent")), ...recent.map((r) =>
      h("button", { type: "button", class: "choice", onclick: () => act(async () => openFile(await platform.readRecent(r.name))) }, icon("open"), h("span", null, h("b", null, r.name))))) : null,
    platform.native ? null : h("p", { class: "hint drop-hint" }, tr("Or drop a file here."))));
}

// ---- tools ---------------------------------------------------------------------------------------------
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
const defaultBox = (pt: [number, number], w: number, hgt: number): Rect => [pt[0] - w / 2, pt[1] - hgt / 2, pt[0] + w / 2, pt[1] + hgt / 2];

viewer.onaction = (a) => act(() => onAction(a));

async function onAction(a: Action) {
  if (!doc) return;
  const d = doc, i = a.page - 1, tool = a.tool, page = a.page;
  const one = { pages: [i] };
  const stroke = { color: rgb(colorOf(tool)), author: author() };
  if (tool === "open-url") {
    if (await confirm(tr("Open link"), a.url, tr("Open"))) platform.openExternal(a.url);
  } else if (tool === "field") {
    await fillField(i, a.field);
  } else if (tool === "no-text") {
    toast(tr("This page has no text to select: it is a scan."));
  } else if (d.readonly) {
    toast(tr("This document is read only."), true);
  } else if (MARKUP_TOOLS.has(tool)) {
    await d.run(`Comment.${cap(tool)}`, { page, start: a.start, stop: a.stop, ...stroke }, { label: tr(cap(tool)), ...one });
  } else if (tool === "rectangle" || tool === "oval") {
    if (a.rect) await d.run(`Comment.${cap(tool)}`, { page, rect: a.rect, width: 1.5, ...stroke }, { label: tr(cap(tool)), ...one });
  } else if (tool === "area-highlight") {
    if (a.rect) await d.run("Comment.AreaHighlight", { page, rect: a.rect, ...stroke }, { label: tr("Area highlight"), ...one });
  } else if (LINE_TOOLS.has(tool)) {
    await d.run(`Comment.${cap(tool)}`, { page, p1: a.p1, p2: a.p2, width: 1.5, ...stroke }, { label: tr(cap(tool)), ...one });
  } else if (tool === "pencil") {
    await d.run("Comment.Pencil", { page, strokes: a.strokes, width: 1.5, ...stroke }, { label: tr("Pencil"), ...one });
  } else if (tool === "note") {
    const text = await prompt(tr("Note"), tr("Note text:"), "", "textarea");
    if (text) await d.run("Comment.Note", { page, point: a.point, text, ...stroke }, { label: tr("Note"), ...one });
  } else if (tool === "typewriter" || tool === "add-text") {
    const size = fontSize();
    const text = await viewer.edit(i, [...a.point, ...a.point] as Rect, { fontsize: size, color: colorOf(tool), multiline: true });
    if (!text?.trim()) return;
    const args = { page, point: a.point, text, fontsize: size, color: rgb(colorOf(tool)) };
    if (tool === "typewriter") await d.run("Comment.Typewriter", { ...args, author: author() }, { label: tr("Typewriter"), ...one });
    else await d.run("Text.Add", args, { label: tr("Add text"), ...one });
  } else if (tool === "textbox") {
    const rect: Rect = a.rect ?? [a.point[0], a.point[1], a.point[0] + 170, a.point[1] + 56];
    const text = await viewer.edit(i, rect, { fontsize: 11, multiline: true, fixed: true });
    if (text?.trim()) await d.run("Comment.Textbox", { page, rect, text, author: author() }, { label: tr("Text box"), ...one });
  } else if (tool === "edit-text") {
    const line = await call("line_at", { sid: d.id, page: i, point: a.point });
    if (!line) return toast(tr("There is no text line here."));
    const text = await viewer.edit(i, line.rect, { value: line.text, fontsize: line.size, color: hex(line.color), fixed: true, grow: true });
    if (text !== null && text !== line.text) await d.run("Text.EditLine", { page, point: a.point, new_text: text }, { label: tr("Edit text"), ...one });
  } else if (tool === "stamp") {
    await d.run("Comment.Stamp", { page, rect: a.rect ?? defaultBox(a.point, 150, 50), name: stampName, author: author() }, { label: tr("Stamp"), ...one });
  } else if (tool === "redact") {
    if (a.rect) await d.run("Redact.MarkRects", { page, rects: [a.rect] }, { label: tr("Mark for redaction"), ...one });
  } else if (tool === "whiteout") {
    if (a.rect) await d.run("Redact.Whiteout", { page, rects: [a.rect] }, { label: tr("Whiteout"), ...one });
  } else if (tool === "sign-place") {
    if (!sign) return;
    const rect = a.rect ?? defaultBox(a.point, 180, 60);
    const image = sign.kind === "image" ? sign : null;
    const spec = image ? { kind: "image", path: file(0) } : sign;
    await d.run("Sign.Place", { page, rect, spec }, { label: tr("Place Signature"), ...one, files: image ? [{ name: image.name, data: signature.imageBytes(image) }] : [] });
    setTool("hand");
  } else if (tool === "image") {
    if (!placing) return;
    const rect = a.rect ?? [a.point[0], a.point[1], a.point[0] + 200, a.point[1] + 200 / placing.ratio];
    await d.run("Sign.Image", { page, rect, path: file(0) }, { label: tr("Add image"), ...one, files: [{ name: placing.name, data: placing.data.slice(0) }] });
    setTool("hand");
  } else if (tool === "move-comment") {
    await d.run("Comment.Move", { page, xref: a.xref, dx: a.dx, dy: a.dy }, { label: tr("Move comment"), ...one });
    await reselect(i, a.xref);
  } else if (tool === "resize-comment") {
    await d.run("Comment.SetRect", { page, xref: a.xref, rect: a.rect }, { label: tr("Resize comment"), ...one });
    await reselect(i, a.xref);
  }
}

async function reselect(i: number, xref: number) {
  const comment = (await doc!.itemsOf(i)).comments.find((c) => c.xref === xref);
  if (comment) viewer.select({ page: i, comment });
}

async function fillField(i: number, f: FormField) {
  const d = doc!;
  if (f.readonly || d.readonly || f.type === "button" || f.type === "unknown") return;
  if (f.type === "signature") return toast(tr("To sign here, use Fill & Sign > Sign and place your signature on the field."));
  const set = (value: unknown) => d.run("Form.SetField", { page: i + 1, xref: f.xref, value }, { label: tr("Fill {field}", { field: f.label || f.name }), pages: [i] });
  if (f.type === "checkbox") return set(!f.value);
  if (f.type === "radio") return set(true);
  const height = f.rect[3] - f.rect[1];
  const value = await viewer.edit(i, f.rect, {
    value: typeof f.value === "string" ? f.value : "", fontsize: f.fontsize || Math.min(12, height * 0.7), multiline: f.multiline, fixed: true,
    options: f.type === "combo" || f.type === "list" ? f.options : undefined,
  });
  if (value !== null && value !== f.value) await set(value);
}

viewer.onselect = () => {
  const d = doc;
  if (!d) return;
  const sel = viewer.selected, text = viewer.textSel;
  if (sel) {
    const c = sel.comment, page = sel.page + 1, one = { pages: [sel.page] };
    const hasText = ["Note", "Typewriter", "Text box", "Callout"].includes(c.kind);
    viewer.showBar(sel.page, c.rect, [
      { label: hasText ? tr("Edit") : tr("Note"), run: () => act(() => editComment(sel.page, c)) },
      { label: tr("Color"), run: () => act(async () => {
        const color = await chooseColor(tr("Color"), hex(c.color.length ? c.color : [1, 0, 0]));
        if (color) await d.run("Comment.SetStyle", { page, xref: c.xref, [c.kind === "Typewriter" ? "text_color" : "color"]: rgb(color) }, { label: tr("Color"), ...one });
      }) },
      { label: tr("Delete"), danger: true, run: () => act(() => d.run("Comment.Delete", { page, xref: c.xref }, { label: tr("Delete comment"), ...one })) },
    ]);
  } else if (text) {
    const page = text.page + 1, one = { pages: [text.page] };
    const box = text.lines.reduce<Rect>((r, l) => [Math.min(r[0], l.rect[0]), Math.min(r[1], l.rect[1]), Math.max(r[2], l.rect[2]), Math.max(r[3], l.rect[3])], [...text.lines[0].rect] as Rect);
    const mark = (tool: string) => ({ label: tr(cap(tool)), run: () => act(() => d.run(`Comment.${cap(tool)}`, { page, start: text.start, stop: text.stop, color: rgb(colorOf(tool)), author: author() }, { label: tr(cap(tool)), ...one })) });
    viewer.showBar(text.page, box, [
      { label: tr("Copy"), run: () => act(async () => { await navigator.clipboard.writeText(viewer.selectedText()); viewer.clearTextSel(); toast(tr("Copied")); }) },
      mark("highlight"), mark("underline"), mark("strikeout"),
      { label: tr("Redact"), run: () => act(() => d.run("Redact.MarkRects", { page, rects: text.lines.map((l) => l.rect) }, { label: tr("Mark for redaction"), ...one })) },
    ]);
  }
};

async function editComment(i: number, c: Comment) {
  const style = await doc!.query("Comment.Style", { page: i + 1, xref: c.xref });
  const text = await prompt(tr(c.kind), tr("Text:"), style.content ?? "", "textarea");
  if (text !== null && text !== style.content) await doc!.run("Comment.SetText", { page: i + 1, xref: c.xref, text }, { label: tr("Edit"), pages: [i] });
}

async function pickColor() {
  const sel = viewer.selected;
  const tool = viewer.tool in DEFAULT_COLORS || RECT_TOOLS.has(viewer.tool) || LINE_TOOLS.has(viewer.tool) || viewer.tool === "pencil" ? viewer.tool : "highlight";
  const color = await chooseColor(sel ? tr("Color") : tr("{tool} color", { tool: tr(cap(tool)) }), sel ? hex(sel.comment.color) : colorOf(tool));
  if (!color) return;
  if (sel) return doc!.run("Comment.SetStyle", { page: sel.page + 1, xref: sel.comment.xref, color: rgb(color) }, { label: tr("Color"), pages: [sel.page] });
  colors[tool] = color;
  store.set("colors", colors);
}

async function pickStamp() {
  const names = ["Approved", "NotApproved", "Draft", "Final", "Confidential", "ForComment", "ForPublicRelease", "NotForPublicRelease", "Expired", "Sold", "TopSecret", "AsIs", "Departmental", "Experimental"];
  const name = await choose(tr("Stamp"), names.map((key) => ({ key, label: tr(key) })));
  if (!name) return;
  stampName = name;
  setTool("stamp");
}

async function startSigning() {
  const kept = signature.saved();
  if (kept) {
    const what = await choose(tr("Sign"), [{ key: "kept", label: tr("Saved Signatures"), icon: "sign", hint: kept.kind === "typed" ? kept.name : undefined },
      { key: "new", label: tr("Create Signature"), icon: "plus" }]);
    if (!what) return;
    sign = what === "kept" ? kept : await signature.create();
  } else sign = await signature.create();
  if (!sign) return;
  setTool("sign-place");
  toast(tr("Tap where the signature goes, or drag a box for its size."));
}

async function startImage() {
  const [f] = await platform.pick(".png,.jpg,.jpeg");
  if (!f) return;
  const bitmap = await createImageBitmap(new Blob([f.data]));
  placing = { name: f.name, data: f.data, ratio: bitmap.width / bitmap.height };
  bitmap.close();
  setTool("image");
}

// ---- commands with a few questions ---------------------------------------------------------------------
const simple = (name: string, label: string, args: object = {}) => doc!.run(name, args, { label });
const here = () => String(viewer.currentPage() + 1);

async function rotatePages(angle: number) {
  const v = await form(angle > 0 ? tr("Rotate Right") : tr("Rotate Left"), [{ key: "pages", label: tr("Pages:"), type: "pages", value: here() }], tr("Rotate"));
  if (v) await simple("Pages.Rotate", angle > 0 ? tr("Rotate right") : tr("Rotate left"), { angle, pages: v.pages || null });
}

async function deletePages() {
  const v = await form(tr("Delete pages"), [{ key: "pages", label: tr("Pages:"), type: "pages", value: here(), placeholder: "1-3,7" }], tr("Delete"), { danger: true });
  if (v?.pages) await simple("Pages.Delete", tr("Delete pages"), { pages: v.pages });
}

async function download(kind: string, args: object) {
  const { meta, data } = await call("export", { sid: doc!.id, kind, ...args });
  const res = await platform.save(meta.name, data, meta.name.endsWith(".pdf") ? "application/pdf" : "application/octet-stream", undefined, true);
  if (res?.message) toast(res.message);
}

async function extractPages(pages?: string) {
  const v = pages ? { pages } : await form(tr("Extract pages"), [{ key: "pages", label: tr("Pages:"), type: "pages", value: here(), placeholder: "1-3,7" }], tr("Extract"));
  if (v?.pages) await download("extract", { pages: v.pages });
}

const insertBlank = (after: number) => simple("Pages.InsertBlank", tr("Insert blank page"), { after });

async function insertFile(after: number) {
  const [f] = await platform.pick(".pdf");
  if (f) await doc!.run("Pages.InsertFile", { path: file(0), after }, { label: tr("Insert pages"), files: [{ name: f.name, data: f.data }] });
}

async function splitDoc() {
  const v = await form(tr("Split Document"), [{ key: "every", label: tr("Pages per file:"), type: "number", value: 1, min: 1, step: 1 }], tr("Split"));
  if (v) await download("split", { every: Math.max(1, Math.round(v.every)) });
}

async function cropWhite() {
  const v = await form(tr("Crop White"), [{ key: "pages", label: tr("Pages:"), type: "pages" }], tr("Crop"));
  if (v) await simple("Pages.Crop", tr("Crop"), { pages: v.pages || null, remove_white: true });
}

async function headerFooter() {
  const row = (key: string, label: string, value = ""): any => ({ key, label, type: "text", value });
  const v = await form(tr("Header & Footer"), [
    { key: "_", label: tr("<<page>> and <<total>> stand for the page number and the page count."), type: "note" },
    row("hl", `${tr("Header")} — ${tr("Left")}`), row("hc", `${tr("Header")} — ${tr("Center")}`), row("hr", `${tr("Header")} — ${tr("Right")}`),
    row("fl", `${tr("Footer")} — ${tr("Left")}`), row("fc", `${tr("Footer")} — ${tr("Center")}`, tr("Page <<page>> of <<total>>")), row("fr", `${tr("Footer")} — ${tr("Right")}`),
    { key: "pages", label: tr("Pages:"), type: "pages" }, { key: "fontsize", label: tr("Font size:"), type: "number", value: 10, min: 4, max: 72 },
  ], tr("Apply"));
  if (v) await simple("Pages.HeaderFooter", tr("Header & footer"), { header: [v.hl, v.hc, v.hr], footer: [v.fl, v.fc, v.fr], pages: v.pages || null, fontsize: v.fontsize || 10 });
}

async function watermark() {
  const v = await form(tr("Add Watermark"), [
    { key: "text", label: tr("Text:"), type: "text", value: tr("CONFIDENTIAL") }, { key: "pages", label: tr("Pages:"), type: "pages" },
    { key: "fontsize", label: tr("Font size:"), type: "number", value: 60, min: 6, max: 300 }, { key: "rotate", label: tr("Rotation:"), type: "number", value: 45, min: -180, max: 180 },
    { key: "opacity", label: tr("Opacity:"), type: "number", value: 0.3, min: 0.05, max: 1, step: 0.05 }, { key: "behind", label: tr("Behind page content"), type: "check" },
  ], tr("Apply"));
  if (v?.text) await simple("Pages.Watermark", tr("Watermark"), { text: v.text, pages: v.pages || null, fontsize: v.fontsize || 60, rotate: v.rotate, opacity: v.opacity || 0.3, behind: v.behind });
}

async function background() {
  const color = await chooseColor(tr("Background"), "#ffffcc");
  if (color) await simple("Pages.Background", tr("Background"), { color: rgb(color) });
}

async function replaceText() {
  const v = await form(tr("Replace Text"), [{ key: "find", label: tr("Find:"), type: "text" }, { key: "replace", label: tr("Replacement text:"), type: "text" },
    { key: "case", label: tr("Match case"), type: "check", value: true }], tr("Replace"));
  if (!v?.find) return;
  const n = await simple("Text.Replace", tr("Replace text"), { find: v.find, replace: v.replace, case_sensitive: v.case });
  toast(tr("{n} replacement(s)", { n }));
}

async function detectLinks() {
  toast(tr("{n} link(s) created", { n: await simple("Links.Detect", tr("Create links")) }));
}

async function searchRedact() {
  const kinds = ["Email address", "Phone number (DE)", "Phone number (US/CA)", "Phone number (international)", "Credit card number", "IBAN",
    "US Social Security number", "Canada Social Insurance number", "German tax ID (Steuer-ID)", "Date"];
  const v = await form(tr("Search & Redact"), [
    { key: "needle", label: tr("Text to mark for redaction:"), type: "text" },
    { key: "kind", label: tr("Find Pattern"), type: "select", value: "", options: [["", tr("None")], ...kinds.map((k) => [k, tr(k)] as [string, string])] },
    { key: "whole", label: tr("Whole words"), type: "check" }, { key: "case", label: tr("Match case"), type: "check" }, { key: "pages", label: tr("Pages:"), type: "pages" },
  ], tr("Mark for Redaction"));
  if (!v || (!v.needle && !v.kind)) return;
  const n = await simple("Redact.Search", tr("Search & redact"), { needle: v.needle || null, kind: v.kind || null, whole_words: v.whole, case_sensitive: v.case, pages: v.pages || null });
  toast(n ? tr("{n} item(s) marked. Use Apply Redactions to remove them for good.", { n }) : tr("Nothing found."));
}

async function applyRedactions() {
  const marks = (await call<any[]>("comments", { sid: doc!.id })).filter((c) => c.type === "Redact").length;
  if (!marks) return toast(tr("Nothing is marked for redaction"));
  if (await confirm(tr("Apply redactions"), tr("Permanently remove {n} marked item(s)? This cannot be undone after saving.", { n: marks }), tr("Apply"), true))
    await simple("Redact.Apply", tr("Apply redactions"));
}

async function passwordProtect() {
  const v = await form(tr("Password Protect"), [
    { key: "user", label: tr("Open password:"), type: "password" }, { key: "again", label: tr("Confirm password:"), type: "password" },
    { key: "owner", label: tr("Permissions password:"), type: "password" },
    { key: "print", label: tr("Allow printing"), type: "check", value: true }, { key: "copy", label: tr("Allow copying text and images"), type: "check", value: true },
    { key: "modify", label: tr("Allow changing the document"), type: "check" }, { key: "annotate", label: tr("Allow comments and form filling"), type: "check", value: true },
  ], tr("Apply"));
  if (!v) return;
  if (!v.user) return toast(tr("Enter the open password twice."), true);
  if (v.user !== v.again) return toast(tr("The passwords do not match."), true);
  await call("protect", { sid: doc!.id, user_pw: v.user, owner_pw: v.owner || null, allow_print: v.print, allow_copy: v.copy, allow_modify: v.modify, allow_annotate: v.annotate });
  await doc!.refresh([]);
  toast(tr("Password protection will be applied when you save"));
}

async function removeSecurity() {
  if (!doc!.protected) return toast(tr("This document has no password protection."));
  await call("unprotect", { sid: doc!.id });
  await doc!.refresh([]);
  toast(tr("Security will be removed when you save"));
}

async function removeHidden() {
  if (await confirm(tr("Remove Hidden Info"), tr("Remove comments, attachments, hidden text, links, scripts and metadata from this document?"), tr("Remove"), true))
    await simple("Protect.RemoveHiddenInfo", tr("Remove hidden info"));
}

async function exportAs(kind: "image" | "text" | "html" | "excel") {
  const pages: any = { key: "pages", label: tr("Pages:"), type: "pages" };
  if (kind === "image") {
    const v = await form(tr("To Image"), [{ key: "format", label: tr("Type:"), type: "select", value: "png", options: [["png", "PNG"], ["jpg", "JPEG"]] },
      { key: "dpi", label: "DPI:", type: "number", value: 150, min: 36, max: 600 }, pages], tr("Export"));
    if (v) await download(v.format, { pages: v.pages || null, dpi: Math.round(v.dpi) || 150 });
  } else {
    const v = await form(tr({ text: "To Text", html: "To HTML", excel: "To Excel" }[kind]), [pages], tr("Export"));
    if (v) await download(kind, { pages: v.pages || null });
  }
}

async function reduceSize() {
  const v = await form(tr("Reduce File Size"), [{ key: "quality", label: tr("Images"), type: "select", value: "medium",
    options: [["minimum", tr("Minimum quality")], ["low", tr("Low quality")], ["medium", tr("Medium quality")], ["high", tr("High quality")]] }], tr("Apply"));
  if (v) await simple("Optimize.Reduce", tr("Reduce file size"), { quality: v.quality });
}

// ---- panels --------------------------------------------------------------------------------------------
function openPages() {
  pagesSheet.show(doc!, viewer.currentPage(), {
    rotate: (pages, angle) => act(() => simple("Pages.Rotate", angle > 0 ? tr("Rotate right") : tr("Rotate left"), { angle, pages })),
    remove: (pages) => act(() => simple("Pages.Delete", tr("Delete pages"), { pages })),
    extract: (pages) => act(() => extractPages(pages)),
    move: (page, before) => act(() => simple("Pages.Move", tr("Reorder pages"), { page, before })),
    insertBlank: (after) => act(() => insertBlank(after)),
    insertFile: (after) => act(() => insertFile(after)),
    goto: (page) => viewer.goto(page),
  });
}

async function showBookmarks() {
  const list = await call<[number, string, number][]>("bookmarks", { sid: doc!.id });
  const s = sheet(tr("Bookmarks"), [list.length ? h("div", { class: "choices" }, ...list.map(([level, text, page]) =>
    h("button", { type: "button", class: "choice", style: { paddingInlineStart: `${level * 14}px` }, onclick: () => { viewer.goto(page - 1); s.close(); } },
      h("span", null, h("b", null, text), h("small", null, tr("Page {n}", { n: page })))))) : h("p", { class: "hint" }, tr("This document has no bookmarks."))]);
}

async function showComments() {
  const list = (await call<any[]>("comments", { sid: doc!.id })).filter((c) => !c.reply_to);
  const s = sheet(tr("Comments"), [list.length ? h("div", { class: "choices" }, ...list.map((c) =>
    h("button", { type: "button", class: "choice", onclick: () => act(async () => { s.close(); viewer.goto(c.page - 1); viewer.reveal(c.page - 1, c.rect); await reselect(c.page - 1, c.xref); }) },
      h("span", null, h("b", null, `${tr(c.kind)} — ${tr("Page {n}", { n: c.page })}`), h("small", null, c.content || c.marked || c.author || ""))))) : h("p", { class: "hint" }, tr("No comments yet."))]);
}

async function gotoPage() {
  const v = await form(tr("Go to"), [{ key: "page", label: tr("Go to page:"), type: "number", value: viewer.currentPage() + 1, min: 1, max: doc!.pages.length, step: 1 }], tr("Go to"));
  if (v) viewer.goto(Math.round(v.page) - 1);
}

// ---- find ----------------------------------------------------------------------------------------------
function toggleFind(show = findBar.hidden) {
  findBar.hidden = !show || !doc;
  if (findBar.hidden) {
    viewer.setHits([]);
    findCount.textContent = "";
    findInput.dataset.last = "";
  } else {
    findInput.focus();
    findInput.select();
  }
}

function stepHit(by: number) {
  viewer.showHit(viewer.hit + by);
  findCount.textContent = viewer.hits.length ? tr("Match {i} of {n}", { i: viewer.hit + 1, n: viewer.hits.length }) : "";
}

findInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") return toggleFind(false);
  if (e.key !== "Enter" || !doc) return;
  const text = findInput.value.trim();
  if (viewer.hits.length && findInput.dataset.last === text) return stepHit(e.shiftKey ? -1 : 1);
  act(async () => {
    findInput.dataset.last = text;
    viewer.setHits(text ? await call("find", { sid: doc!.id, text }) : []);
    if (viewer.hits.length) {
      const from = viewer.currentPage();
      viewer.hit = Math.max(0, viewer.hits.findIndex((x) => x.page >= from)) - 1;
      stepHit(1);
    } else findCount.textContent = text ? tr("Nothing found.") : "";
  });
});

// ---- keys, drops, leaving ------------------------------------------------------------------------------
viewer.onpage = showPage;

document.addEventListener("keydown", (e) => {
  if (document.querySelector("dialog[open]") || (e.target as HTMLElement).closest("input, textarea, select")) return;
  const mod = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
  const go = (fn: () => unknown) => { e.preventDefault(); act(fn); };
  if (mod && key === "o") go(openDialog);
  else if (!doc) return;
  else if (mod && key === "s") go(() => (e.shiftKey ? saveAs() : save()));
  else if (mod && key === "z") go(() => undo(e.shiftKey));
  else if (mod && key === "y") go(() => undo(true));
  else if (mod && key === "f") go(() => toggleFind(true));
  else if (mod && key === "p") go(printDoc);
  else if (mod && (key === "=" || key === "+")) go(() => viewer.setZoom(viewer.zoom * 1.25));
  else if (mod && key === "-") go(() => viewer.setZoom(viewer.zoom / 1.25));
  else if (mod && key === "0") go(() => viewer.fitPage());
  else if (key === "escape") setTool("hand");
  else if ((key === "delete" || key === "backspace") && viewer.selected) {
    const sel = viewer.selected;
    go(() => doc!.run("Comment.Delete", { page: sel.page + 1, xref: sel.comment.xref }, { label: tr("Delete comment"), pages: [sel.page] }));
  }
});

document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer?.files[0];
  if (f) act(async () => openFile({ name: f.name, data: await f.arrayBuffer() }));
});
window.addEventListener("beforeunload", (e) => {
  if (doc?.modified) e.preventDefault();
});
if (platform.native) {
  SystemBars.setStyle({ style: SystemBarsStyle.Dark, bar: SystemBarType.StatusBar }).catch(() => {});      // light clock on the red bar
  App.addListener("backButton", () => {
    const open = document.querySelector<HTMLDialogElement>("dialog[open]");
    if (open) open.close();
    else if (!findBar.hidden) toggleFind(false);
    else if (viewer.tool !== "hand") setTool("hand");
    else if (doc) act(closeDoc);
    else App.exitApp();
  });
}

/** Called once Python runs and the language is set (main.ts). */
export async function init(incoming: platform.Picked[], later: (open: (f: platform.Picked) => void) => void) {
  commands = new Set(await call<string[]>("available"));
  buildRibbon();
  refresh();
  await showStart();
  later((f) => act(() => openFile(f)));
  if (incoming.length) await act(() => openFile(incoming[0]));
}
