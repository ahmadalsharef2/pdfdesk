// Small DOM helpers: h() builds elements; sheets, menus and toasts are the app's dialogs.
import { icon } from "./icons";
import { tr } from "./i18n";

type Kid = Node | string | null | undefined | false;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Record<string, any> | null, ...kids: Kid[]) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") Object.assign(el.style, v);
    else if (k in el && k !== "list") (el as any)[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  el.append(...(kids.filter((k) => k != null && k !== false) as (Node | string)[]));
  return el;
}

export function button(label: string, onclick: () => void, opts: { icon?: string; primary?: boolean; danger?: boolean } = {}) {
  return h("button", { type: "button", class: "btn" + (opts.primary ? " primary" : "") + (opts.danger ? " danger" : ""), onclick },
    opts.icon ? icon(opts.icon) : null, label);
}

export function iconButton(name: string, label: string, onclick: (e: MouseEvent) => void) {
  return h("button", { type: "button", class: "icon-btn", title: label, "aria-label": label, onclick }, icon(name));
}

let toastTimer = 0;
export function toast(text: string, error = false) {
  let el = document.querySelector<HTMLElement>(".toast");
  if (!el) document.body.append((el = h("div", { class: "toast", role: "status" })));
  el.textContent = text;
  el.classList.toggle("error", error);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el!.classList.remove("show"), error ? 6000 : 3200);
}

/** A modal sheet: slides up from the bottom on a phone, a centred dialog on a wide screen. */
export function sheet(title: string, body: Kid[], opts: { wide?: boolean; onClose?: () => void } = {}) {
  const dlg = h("dialog", { class: "sheet" + (opts.wide ? " wide" : "") });
  const close = () => dlg.close();
  dlg.append(
    h("header", null, h("h2", null, title), iconButton("close", tr("Close"), close)),
    h("div", { class: "sheet-body" }, ...body),
  );
  dlg.addEventListener("close", () => {
    dlg.remove();
    opts.onClose?.();
  });
  dlg.addEventListener("click", (e) => e.target === dlg && close());       // a tap on the backdrop
  document.body.append(dlg);
  dlg.showModal();
  return { el: dlg, close };
}

export type Field =
  | { key: string; label: string; type: "text" | "password" | "number" | "pages" | "textarea"; value?: string | number; placeholder?: string; min?: number; max?: number; step?: number }
  | { key: string; label: string; type: "select"; value?: string; options: [string, string][] }
  | { key: string; label: string; type: "check"; value?: boolean }
  | { key: string; label: string; type: "color"; value?: string }
  | { key: string; label: string; type: "note" };

/** Ask for a few values. Resolves with them, or null when the sheet is closed without the action. */
export function form(title: string, fields: Field[], action: string, opts: { danger?: boolean } = {}): Promise<Record<string, any> | null> {
  return new Promise((resolve) => {
    let result: Record<string, any> | null = null;
    const inputs = new Map<string, HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>();
    const rows = fields.map((f) => {
      if (f.type === "note") return h("p", { class: "hint" }, f.label);
      let input: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
      if (f.type === "select") {
        input = h("select", null, ...f.options.map(([v, text]) => h("option", { value: v, selected: v === f.value }, text)));
      } else if (f.type === "check") {
        input = h("input", { type: "checkbox", checked: !!f.value });
      } else if (f.type === "textarea") {
        input = h("textarea", { rows: 4, value: String(f.value ?? ""), placeholder: f.placeholder });
      } else {
        input = h("input", {
          type: f.type === "pages" ? "text" : f.type, value: String(f.value ?? ""), min: (f as any).min, max: (f as any).max,
          step: (f as any).step, placeholder: (f as any).placeholder ?? (f.type === "pages" ? tr("all (e.g. 1-3,7, odd, even)") : undefined),
          inputMode: f.type === "number" ? "decimal" : undefined, autocomplete: f.type === "password" ? "new-password" : "off",
        });
      }
      inputs.set(f.key, input);
      return f.type === "check" ? h("label", { class: "row check" }, input, h("span", null, f.label))
        : h("label", { class: "row" }, h("span", null, f.label), input);
    });
    const submit = (e: Event) => {
      e.preventDefault();
      result = {};
      for (const f of fields) {
        const el = inputs.get(f.key);
        if (!el) continue;
        result[f.key] = f.type === "check" ? (el as HTMLInputElement).checked : f.type === "number" ? Number(el.value) : el.value;
      }
      s.close();
    };
    const s = sheet(title, [h("form", { onsubmit: submit }, ...rows,
      h("div", { class: "actions" }, button(tr("Cancel"), () => s.close()),
        h("button", { type: "submit", class: "btn primary" + (opts.danger ? " danger" : "") }, action)))],
      { onClose: () => resolve(result) });
    const first = s.el.querySelector<HTMLElement>("input:not([type=checkbox]),textarea,select");
    if (first && matchMedia("(pointer: fine)").matches) first.focus();
  });
}

export function confirm(title: string, text: string, action: string, danger = false): Promise<boolean> {
  return form(title, [{ key: "_", label: text, type: "note" }], action, { danger }).then((v) => v !== null);
}

export async function prompt(title: string, label: string, value = "", type: "text" | "password" | "textarea" = "text"): Promise<string | null> {
  const v = await form(title, [{ key: "v", label, type, value }], tr("OK"));
  return v ? String(v.v) : null;
}

/** A list of choices in a sheet; resolves with the chosen key. */
export function choose<T extends string>(title: string, items: { key: T; label: string; icon?: string; hint?: string }[]): Promise<T | null> {
  return new Promise((resolve) => {
    let picked: T | null = null;
    const s = sheet(title, [h("div", { class: "choices" }, ...items.map((it) =>
      h("button", { type: "button", class: "choice", onclick: () => { picked = it.key; s.close(); } },
        it.icon ? icon(it.icon) : null, h("span", null, h("b", null, it.label), it.hint ? h("small", null, it.hint) : null))))],
      { onClose: () => resolve(picked) });
  });
}

/** A spinner over the page while something long runs; call the result to remove it. */
export function busy(text: string) {
  const el = h("div", { class: "busy", role: "status" }, h("div", { class: "spinner" }), h("span", null, text));
  document.body.append(el);
  return () => el.remove();
}

export const COLORS: [string, string][] = [["#ffd900", "Yellow"], ["#e61a1a", "Red"], ["#009900", "Green"], ["#1a4de6", "Blue"],
  ["#ff8c00", "Orange"], ["#b040d0", "Purple"], ["#000000", "Black"], ["#ffffff", "White"]];
export const rgb = (hex: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as [number, number, number];
export const hex = (c: number[]) => "#" + c.slice(0, 3).map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");

export function chooseColor(title: string, current?: string): Promise<string | null> {
  return new Promise((resolve) => {
    let picked: string | null = null;
    const pick = (c: string) => { picked = c; s.close(); };
    const custom = h("input", { type: "color", value: current ?? "#e61a1a", "aria-label": tr("More colors…"), onchange: () => pick(custom.value) });
    const s = sheet(title, [h("div", { class: "swatches" }, ...COLORS.map(([c, name]) =>
      h("button", { type: "button", class: "swatch" + (c === current ? " on" : ""), style: { background: c }, title: tr(name), "aria-label": tr(name), onclick: () => pick(c) })),
      h("label", { class: "swatch custom", title: tr("More colors…") }, custom))], { onClose: () => resolve(picked) });
  });
}
