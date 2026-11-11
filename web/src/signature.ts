// Create Signature: draw it, type it or choose a picture of it. The result is the `spec` Sign.Place takes.
import { button, h, sheet } from "./dom";
import { tr } from "./i18n";
import { pick } from "./platform";

export type Signature =
  | { kind: "ink"; strokes: [number, number][][]; size: [number, number] }
  | { kind: "typed"; name: string }
  | { kind: "image"; name: string; data: string };            // data: base64, so it can be kept for next time

const KEY = "pdfdesk.signature";

export function saved(): Signature | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "null");
  } catch {
    return null;
  }
}

export function imageBytes(s: { data: string }): ArrayBuffer {
  const bin = atob(s.data);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

export function create(): Promise<Signature | null> {
  return new Promise((resolve) => {
    let result: Signature | null = null;
    let mode: "ink" | "typed" | "image" = "ink";
    let image: { name: string; data: string } | null = null;
    const strokes: [number, number][][] = [];
    const canvas = h("canvas", { class: "sign-pad", width: 600, height: 240 });
    const ctx = canvas.getContext("2d")!;
    const redraw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineWidth = 3.2;
      ctx.lineCap = ctx.lineJoin = "round";
      ctx.strokeStyle = "#00008c";
      for (const s of strokes) {
        ctx.beginPath();
        s.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        if (s.length === 1) ctx.lineTo(s[0][0] + 0.1, s[0][1] + 0.1);
        ctx.stroke();
      }
    };
    const at = (e: PointerEvent): [number, number] => {
      const r = canvas.getBoundingClientRect();
      return [((e.clientX - r.left) / r.width) * canvas.width, ((e.clientY - r.top) / r.height) * canvas.height];
    };
    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      strokes.push([at(e)]);
      redraw();
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!canvas.hasPointerCapture(e.pointerId)) return;
      strokes[strokes.length - 1].push(at(e));
      redraw();
    });
    const name = h("input", { type: "text", class: "sign-name", placeholder: tr("Full name"), autocomplete: "name" });
    const typed = h("div", { class: "sign-typed" });
    name.addEventListener("input", () => (typed.textContent = name.value));
    const preview = h("img", { class: "sign-image", alt: "" });
    const choose = button(tr("Choose image…"), async () => {
      const [f] = await pick(".png,.jpg,.jpeg");
      if (!f) return;
      let bin = "";
      const bytes = new Uint8Array(f.data);
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      image = { name: f.name, data: btoa(bin) };
      preview.src = `data:image/${f.name.toLowerCase().endsWith(".png") ? "png" : "jpeg"};base64,${image.data}`;
    }, { icon: "image" });
    const panes = {
      ink: h("div", { class: "sign-pane" }, canvas, button(tr("Clear"), () => { strokes.length = 0; redraw(); })),
      typed: h("div", { class: "sign-pane" }, name, typed),
      image: h("div", { class: "sign-pane" }, choose, preview),
    };
    const tabs = h("div", { class: "segments", role: "tablist" });
    const show = (m: typeof mode) => {
      mode = m;
      for (const [k, el] of Object.entries(panes)) el.hidden = k !== m;
      [...tabs.children].forEach((b) => b.classList.toggle("on", (b as HTMLElement).dataset.mode === m));
    };
    for (const [m, label] of [["ink", tr("Draw")], ["typed", tr("Type")], ["image", tr("Image")]] as const) {
      const b = h("button", { type: "button", role: "tab", onclick: () => show(m) }, label);
      b.dataset.mode = m;
      tabs.append(b);
    }
    const keep = h("input", { type: "checkbox", checked: true });
    const use = () => {
      if (mode === "ink" && strokes.length) result = { kind: "ink", strokes, size: [canvas.width, canvas.height] };
      else if (mode === "typed" && name.value.trim()) result = { kind: "typed", name: name.value.trim() };
      else if (mode === "image" && image) result = { kind: "image", ...image };
      else return;
      try {
        if (keep.checked) localStorage.setItem(KEY, JSON.stringify(result));
        else localStorage.removeItem(KEY);
      } catch { /* too big to keep, or private mode: it still signs now */ }
      s.close();
    };
    const s = sheet(tr("Create Signature"), [tabs, panes.ink, panes.typed, panes.image,
      h("label", { class: "row check" }, keep, h("span", null, tr("Save this signature for next time"))),
      h("div", { class: "actions" }, button(tr("Cancel"), () => s.close()), button(tr("Use Now"), use, { primary: true }))],
      { onClose: () => resolve(result) });
    show("ink");
  });
}
