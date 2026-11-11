// The page view: pages in one scrolling column, rendered by the Python side as they come into view, with an
// overlay per page for selections and tool previews. Gestures end in actions ({tool, page, ...} in unrotated
// page points, page 1-based) that the app turns into commands, as the desktop view's toolAction does.
import { apply, applyRect, inside, textBetween, type Comment, type Doc, type Items, type Pt, type Rect, type Word } from "./doc";
import { h } from "./dom";
import { call } from "./engine";

export const RECT_TOOLS = new Set(["textbox", "rectangle", "oval", "area-highlight", "redact", "whiteout", "sign-place", "image", "stamp"]);
export const LINE_TOOLS = new Set(["line", "arrow"]);
export const MARKUP_TOOLS = new Set(["highlight", "underline", "strikeout", "squiggly"]);
export const POINT_TOOLS = new Set(["note", "typewriter", "add-text", "edit-text"]);
const TEXT_TOOLS = new Set([...MARKUP_TOOLS, "select"]);
const DASHED = new Set(["textbox", "sign-place", "image", "stamp"]);            // a box that shows where something goes

export type Action = { tool: string; page: number; [key: string]: any };
export type BarButton = { label: string; run: () => void; danger?: boolean };
type View = { el: HTMLElement; canvas: HTMLCanvasElement | null; overlay: SVGSVGElement; key: string; detail: HTMLCanvasElement | null };
type Gesture = {
  kind: "tap" | "pan" | "text" | "rect" | "line" | "ink" | "point" | "move" | "resize";
  id: number; page: number; start: Pt; cur: Pt; x: number; y: number; moved: boolean; words?: Word[]; stroke?: Pt[]; corner?: string;
};

const GAP = 10;
const coarse = matchMedia("(pointer: coarse)").matches;
const MAX_PIXELS = coarse ? 5e6 : 16e6;       // per page bitmap; beyond it the visible part is drawn again, sharp
const svg = (tag: string, attrs: Record<string, string | number>) =>
  `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ")}/>`;
const box = (r: Rect) => ({ x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1] });
const norm = (a: Pt, b: Pt): Rect => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];

export class Viewer {
  el = h("div", { class: "viewer tool-hand", dir: "ltr", tabIndex: 0 });
  private sheet = h("div", { class: "pages" });
  doc: Doc | null = null;
  zoom = 1;
  fit: "width" | "page" | null = "width";
  tool = "hand";
  selected: { page: number; comment: Comment } | null = null;
  textSel: { page: number; start: Pt; stop: Pt; lines: { rect: Rect; text: string }[] } | null = null;
  hits: { page: number; rect: Rect }[] = [];
  hit = -1;
  onaction: (a: Action) => void = () => {};
  onpage: () => void = () => {};
  onselect: () => void = () => {};
  style: (tool: string) => { color: string; width: number } = () => ({ color: "#e61a1a", width: 1.5 });

  private views: View[] = [];
  private prefix: number[] = [0];              // heights of the pages before each page, in points
  private widest = 1;
  private items = new Map<number, { rev: number; items: Items }>();
  private gesture: Gesture | null = null;
  private pinch: { d0: number; z0: number; at: { i: number; fx: number; fy: number } } | null = null;
  private ink: { page: number; strokes: Pt[][] } | null = null;
  private sent: { page: number; strokes: Pt[][]; rev: number } | null = null;      // handed over, not yet in the bitmap
  private inkTimer = 0;
  private rendering = false;
  private settle = 0;
  private bar: HTMLElement | null = null;
  private selBox: HTMLElement | null = null;
  private editor: { el: HTMLElement; done: (commit: boolean) => void } | null = null;
  private frame = 0;

  constructor() {
    this.el.append(this.sheet);
    this.el.addEventListener("scroll", () => this.scrolled(), { passive: true });
    this.sheet.addEventListener("pointerdown", (e) => this.down(e));
    this.sheet.addEventListener("pointermove", (e) => this.move(e));
    this.sheet.addEventListener("pointerup", (e) => this.up(e));
    this.sheet.addEventListener("pointercancel", () => this.cancel());
    this.el.addEventListener("touchstart", (e) => this.touch(e), { passive: false });
    this.el.addEventListener("touchmove", (e) => this.touch(e), { passive: false });
    this.el.addEventListener("touchend", (e) => this.touch(e));
    this.el.addEventListener("touchcancel", (e) => this.touch(e));
    this.el.addEventListener("wheel", (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      this.setZoom(this.zoom * Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.01), { x: e.clientX, y: e.clientY });
    }, { passive: false });
    new ResizeObserver(() => this.resized()).observe(this.el);
  }

  // ---- document and layout ----------------------------------------------------------------------------
  setDoc(doc: Doc | null) {
    this.flushInk();
    this.closeEditor(false);
    this.doc = doc;
    this.selected = this.textSel = null;
    this.hits = [];
    this.hit = -1;
    this.items.clear();
    this.sheet.replaceChildren();
    this.views = [];
    this.hideBar();
    if (!doc) return;
    this.sync();
    this.fit = "width";
    this.refit();
    if (this.zoom > 1.6) this.setZoom(1.25);     // a wide window: the full width would make the text huge
    this.el.scrollTop = 0;
    this.el.scrollLeft = (this.el.scrollWidth - this.el.clientWidth) / 2;
    this.pump();
  }

  /** The document changed: match the page elements to its pages, keeping what is drawn until it is redrawn. */
  changed(pagesChanged: boolean) {
    if (!this.doc) return;
    const at = this.locate(this.el.clientWidth / 2, 0);
    if (this.selected && !this.gesture) this.select(null);
    this.textSel = null;
    this.hideBar();
    if (pagesChanged) {
      this.hits = [];
      this.hit = -1;
      this.sync();
      if (this.fit) this.refit();
      else this.place(at, this.el.clientWidth / 2, 0);
    }
    for (let i = 0; i < this.views.length; i++) this.paint(i);
    this.pump();
    this.onpage();
  }

  private sync() {
    const pages = this.doc!.pages;
    while (this.views.length > pages.length) this.views.pop()!.el.remove();
    while (this.views.length < pages.length) {
      const overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      overlay.setAttribute("class", "overlay");
      const el = h("div", { class: "page" }, overlay as unknown as Node);
      el.dataset.page = String(this.views.length);
      this.sheet.append(el);
      this.views.push({ el, canvas: null, overlay, key: "", detail: null });
    }
    this.prefix = [0];
    this.widest = 1;
    pages.forEach((p, i) => {
      const v = this.views[i];
      v.el.style.setProperty("--w", String(p.w));
      v.el.style.setProperty("--h", String(p.h));
      v.overlay.setAttribute("viewBox", `0 0 ${p.w} ${p.h}`);
      this.prefix.push(this.prefix[i] + p.h);
      this.widest = Math.max(this.widest, p.w);
    });
    this.sheet.style.setProperty("--z", String(this.zoom));
  }

  private top = (i: number) => GAP + i * GAP + this.zoom * this.prefix[i];
  private left = (i: number) => (Math.max(this.el.clientWidth, this.widest * this.zoom + 2 * GAP) - this.doc!.pages[i].w * this.zoom) / 2;

  /** The page under a point of the viewport, and where in the page (as fractions of its size). */
  private locate(x: number, y: number) {
    const pages = this.doc!.pages;
    const yy = this.el.scrollTop + y;
    let lo = 0, hi = pages.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.top(mid) <= yy) lo = mid;
      else hi = mid - 1;
    }
    const p = pages[lo];
    return { i: lo, fx: (this.el.scrollLeft + x - this.left(lo)) / (p.w * this.zoom), fy: (yy - this.top(lo)) / (p.h * this.zoom) };
  }

  private place(at: { i: number; fx: number; fy: number }, x: number, y: number) {
    const i = Math.min(at.i, this.doc!.pages.length - 1), p = this.doc!.pages[i];
    this.el.scrollTop = this.top(i) + at.fy * p.h * this.zoom - y;
    this.el.scrollLeft = this.left(i) + at.fx * p.w * this.zoom - x;
  }

  setZoom(z: number, anchor?: { x: number; y: number }, fit: "width" | "page" | null = null) {
    if (!this.doc?.pages.length) return;
    const r = this.el.getBoundingClientRect();
    const x = anchor ? anchor.x - r.left : r.width / 2, y = anchor ? anchor.y - r.top : r.height / 2;
    this.zoomAt(z, this.locate(x, y), x, y);
    this.fit = fit;
  }

  private zoomAt(z: number, at: { i: number; fx: number; fy: number }, x: number, y: number) {
    this.zoom = Math.max(0.1, Math.min(8, z));
    this.sheet.style.setProperty("--z", String(this.zoom));
    this.place(at, x, y);
    if (this.bar) this.onselect();               // its place is in pixels
    clearTimeout(this.settle);                   // draw once the zoom stops changing, not at every step
    this.settle = window.setTimeout(() => { this.settle = 0; this.pump(); }, 140);
    this.onpage();
  }

  private refit() {
    if (!this.doc?.pages.length || !this.el.clientWidth) return;
    const page = this.doc.pages[this.currentPage()];
    const width = (this.el.clientWidth - 2 * GAP) / (this.fit === "page" ? page.w : this.widest);
    const z = this.fit === "page" ? Math.min(width, (this.el.clientHeight - 2 * GAP) / page.h) : width;
    const at = this.locate(this.el.clientWidth / 2, 0);
    this.zoomAt(z, { i: at.i, fx: 0.5, fy: this.fit === "page" ? -GAP / (page.h * z) : at.fy }, this.el.clientWidth / 2, 0);
  }

  fitWidth() { this.fit = "width"; this.refit(); }
  fitPage() { this.fit = "page"; this.refit(); }
  private resized() { if (this.fit) this.refit(); else this.pump(); }

  currentPage(): number {
    return this.doc?.pages.length ? this.locate(0, this.el.clientHeight * 0.3).i : 0;
  }

  goto(i: number, y = 0) {
    if (!this.doc?.pages.length) return;
    i = Math.max(0, Math.min(this.doc.pages.length - 1, i));
    this.el.scrollTop = this.top(i) - GAP / 2 + Math.max(0, y) * this.zoom;
  }

  /** Bring a part of a page into view if it is not. */
  reveal(i: number, rect: Rect) {
    const r = applyRect(this.doc!.pages[i].m, rect);
    const y = this.top(i) + r[1] * this.zoom, x = this.left(i) + r[0] * this.zoom;
    if (y < this.el.scrollTop + 20 || y > this.el.scrollTop + this.el.clientHeight - 80) this.el.scrollTop = y - this.el.clientHeight / 3;
    if (x < this.el.scrollLeft || x > this.el.scrollLeft + this.el.clientWidth - 40) this.el.scrollLeft = x - this.el.clientWidth / 3;
  }

  private scrolled() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.pump();
      this.onpage();
    });
  }

  // ---- rendering --------------------------------------------------------------------------------------
  private visible(): [number, number] {
    const first = this.locate(0, 0).i;
    let last = first;
    while (last + 1 < this.views.length && this.top(last + 1) < this.el.scrollTop + this.el.clientHeight) last++;
    return [first, last];
  }

  /** Draw the page that needs it most, then look again: the Python side renders one page at a time. */
  private async pump(): Promise<void> {
    const doc = this.doc;
    if (this.rendering || this.settle || !doc?.pages.length || !this.el.clientHeight) return;
    const [first, last] = this.visible();
    const dpr = window.devicePixelRatio || 1;
    const order = [];
    for (let i = first; i <= last; i++) order.push(i);
    order.push(last + 1, first - 1);
    this.views.forEach((v, i) => {              // pages far from view give their bitmaps back
      if ((i < first - 2 || i > last + 2) && v.canvas) {
        v.canvas.remove();
        v.detail?.remove();
        v.canvas = v.detail = null;
        v.key = "";
      }
    });
    for (const i of order) {
      const p = doc.pages[i], v = this.views[i];
      if (!p) continue;
      const want = this.zoom * dpr;
      const scale = Math.min(want, Math.sqrt(MAX_PIXELS / (p.w * p.h)));
      const key = `${p.rev}@${scale.toFixed(3)}`;
      if (!this.items.has(i) || this.items.get(i)!.rev !== p.rev) this.loadItems(i);
      if (v.key === key) {
        if (scale < want * 0.97 && i >= first && i <= last && (await this.sharpen(doc, i, want))) return this.pump();
        continue;
      }
      this.rendering = true;
      try {
        const { meta, data } = await call("render", { sid: doc.id, page: i, scale });
        if (this.doc === doc && this.views[i] === v) {
          if (!v.canvas) v.el.prepend((v.canvas = h("canvas", { class: "bitmap" })));
          v.canvas.width = meta.width;
          v.canvas.height = meta.height;
          v.canvas.getContext("2d")!.putImageData(new ImageData(new Uint8ClampedArray(data.buffer as ArrayBuffer), meta.width, meta.height), 0, 0);
          v.key = key;
          v.detail?.remove();
          v.detail = null;
          if (this.sent?.page === i && this.sent.rev !== p.rev) {
            this.sent = null;
            this.paint(i);
          }
        }
      } catch (e) {
        console.error(e);
        v.key = key;                             // do not ask again and again for a page that cannot be drawn
      } finally {
        this.rendering = false;
      }
      return this.pump();
    }
  }

  /** Zoomed in beyond what one bitmap of the page can hold: draw the part in view (and a margin) again, sharp,
   * on top. Returns whether it drew. */
  private async sharpen(doc: Doc, i: number, scale: number): Promise<boolean> {
    const p = doc.pages[i], v = this.views[i];
    const span = (from: number, size: number, max: number, grow: number): [number, number] =>
      [Math.max(0, Math.min(max, from / this.zoom - grow)), Math.max(0, Math.min(max, (from + size) / this.zoom + grow))];
    const see = [span(this.el.scrollLeft - this.left(i), this.el.clientWidth, p.w, 0), span(this.el.scrollTop - this.top(i), this.el.clientHeight, p.h, 0)];
    if (see[0][1] - see[0][0] < 1 || see[1][1] - see[1][0] < 1) return false;
    const have = v.detail?.dataset.key === `${p.rev}@${scale.toFixed(3)}` ? v.detail.dataset.area!.split(",").map(Number) : null;
    if (have && have[0] <= see[0][0] && have[1] <= see[1][0] && have[2] >= see[0][1] && have[3] >= see[1][1]) return false;
    const [x, y] = [span(this.el.scrollLeft - this.left(i), this.el.clientWidth, p.w, this.el.clientWidth / this.zoom / 4),
      span(this.el.scrollTop - this.top(i), this.el.clientHeight, p.h, this.el.clientHeight / this.zoom / 4)];
    const clip = [x[0], y[0], x[1], y[1]];
    this.rendering = true;
    try {
      const { meta, data } = await call("render", { sid: doc.id, page: i, scale, clip });
      if (this.doc !== doc || this.views[i] !== v || !v.canvas) return true;
      const detail = h("canvas", { class: "detail", width: meta.width, height: meta.height });
      detail.dataset.key = `${p.rev}@${scale.toFixed(3)}`;
      detail.dataset.area = clip.join(",");
      Object.assign(detail.style, { left: `${(clip[0] / p.w) * 100}%`, top: `${(clip[1] / p.h) * 100}%`, width: `${((clip[2] - clip[0]) / p.w) * 100}%`, height: `${((clip[3] - clip[1]) / p.h) * 100}%` });
      detail.getContext("2d")!.putImageData(new ImageData(new Uint8ClampedArray(data.buffer as ArrayBuffer), meta.width, meta.height), 0, 0);
      v.detail?.remove();
      v.canvas.after((v.detail = detail));
    } catch (e) {
      console.error(e);
      return false;
    } finally {
      this.rendering = false;
    }
    return true;
  }

  private loadItems(i: number) {
    const doc = this.doc!, rev = doc.pages[i].rev;
    this.items.set(i, { rev, items: this.items.get(i)?.items ?? { comments: [], fields: [], links: [] } });
    doc.itemsOf(i).then((items) => {
      if (this.doc !== doc || doc.pages[i]?.rev !== rev) return;
      this.items.set(i, { rev, items });
      this.paint(i);
    }, () => {});
  }

  // ---- overlay ----------------------------------------------------------------------------------------
  private paint(i: number) {
    const v = this.views[i], p = this.doc?.pages[i];
    if (!v || !p) return;
    const out: string[] = [];
    const R = (r: Rect, cls: string, extra: Record<string, string | number> = {}) => out.push(svg("rect", { ...box(applyRect(p.m, r)), class: cls, ...extra }));
    for (const f of this.items.get(i)?.items.fields ?? []) if (!f.readonly) R(f.rect, "field");
    this.hits.forEach((hit, k) => hit.page === i && R(hit.rect, k === this.hit ? "hit on" : "hit"));
    if (this.textSel?.page === i) for (const ln of this.textSel.lines) R(ln.rect, "tsel");
    const g = this.gesture;
    if (g && g.page === i && g.moved) {
      const { color, width } = this.style(this.tool);
      if (g.kind === "text" && g.words) {
        for (const ln of textBetween(g.words, g.start, g.cur)) R(ln.rect, "tsel", this.tool === "select" ? {} : { style: `fill:${color}` });
      } else if (g.kind === "rect") {
        const r = box(applyRect(p.m, norm(g.start, g.cur)));
        const look: Record<string, string | number> = this.tool === "redact" ? { fill: "#000", "fill-opacity": 0.55, stroke: "#d33a3a" }
          : this.tool === "whiteout" ? { fill: "#fff", "fill-opacity": 0.85, stroke: "#888" }
          : this.tool === "area-highlight" ? { fill: color, "fill-opacity": 0.4, stroke: "none" }
          : DASHED.has(this.tool) ? { fill: "#2b6cc4", "fill-opacity": 0.08, stroke: "#2b6cc4", "stroke-dasharray": "4 3" }
          : { fill: "none", stroke: color, "stroke-width": width };
        out.push(this.tool === "oval" ? svg("ellipse", { cx: r.x + r.width / 2, cy: r.y + r.height / 2, rx: r.width / 2, ry: r.height / 2, ...look }) : svg("rect", { ...r, ...look }));
      } else if (g.kind === "line") {
        const a = apply(p.m, g.start), b = apply(p.m, g.cur);
        out.push(svg("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: color, "stroke-width": width, "stroke-linecap": "round" }));
      }
    }
    const strokes = [...(this.sent?.page === i ? this.sent.strokes : []), ...(this.ink?.page === i ? this.ink.strokes : []),
      ...(g?.kind === "ink" && g.page === i ? [g.stroke!] : [])];
    if (strokes.length) {
      const { color, width } = this.style("pencil");
      for (const s of strokes)
        out.push(svg("polyline", { points: s.map((q) => apply(p.m, q).map((n) => n.toFixed(1)).join(",")).join(" "), fill: "none", stroke: color, "stroke-width": width, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    }
    v.overlay.innerHTML = out.join("");
  }

  private toPage(i: number, e: { clientX: number; clientY: number }): Pt {
    const p = this.doc!.pages[i], r = this.views[i].el.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * p.w, y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) * p.h;
    return apply(p.inv, [x, y]);
  }

  /** Where a page rectangle is inside its page element, in percent, so it follows any zoom. */
  private percent(i: number, rect: Rect) {
    const p = this.doc!.pages[i], r = applyRect(p.m, rect);
    return { left: `${(r[0] / p.w) * 100}%`, top: `${(r[1] / p.h) * 100}%`, width: `${((r[2] - r[0]) / p.w) * 100}%`, height: `${((r[3] - r[1]) / p.h) * 100}%` };
  }

  // ---- tools and gestures -----------------------------------------------------------------------------
  setTool(tool: string) {
    this.flushInk();
    this.closeEditor(true);
    this.el.classList.replace("tool-" + this.tool, "tool-" + tool);
    this.tool = tool;
    this.el.classList.toggle("drawing", tool !== "hand");
    if (tool !== "hand" && tool !== "select") this.select(null);
    this.clearTextSel();
  }

  private down(e: PointerEvent) {
    if (!this.doc || this.pinch || this.gesture || (e.pointerType === "mouse" && e.button !== 0)) return;
    const target = e.target as HTMLElement;
    if (target.closest(".bar, .editor")) return;
    const pageEl = target.closest<HTMLElement>(".page");
    const grip = target.closest<HTMLElement>(".sel");
    const tool = this.tool;
    if (!pageEl) {
      if (e.pointerType === "mouse" && tool === "hand") this.begin(e, "pan", 0);
      return;
    }
    const i = Number(pageEl.dataset.page);
    this.closeEditor(true);
    if (grip && this.selected) {
      const corner = target.dataset.corner;
      return void (this.begin(e, corner ? "resize" : "move", i).corner = corner);
    }
    const kind = tool === "hand" ? (e.pointerType === "mouse" ? "pan" : "tap") : TEXT_TOOLS.has(tool) ? "text" : RECT_TOOLS.has(tool) ? "rect"
      : LINE_TOOLS.has(tool) ? "line" : tool === "pencil" ? "ink" : "point";
    const g = this.begin(e, kind, i);
    if (kind === "text") this.doc.wordsOf(i).then((w) => (g.words = w), () => {});
    if (kind === "ink") {
      if (this.ink && this.ink.page !== i) this.flushInk();
      clearTimeout(this.inkTimer);
      g.stroke = [g.start];
    }
  }

  private begin(e: PointerEvent, kind: Gesture["kind"], i: number): Gesture {
    const pt = this.toPage(i, e);
    if (kind !== "tap") this.sheet.setPointerCapture(e.pointerId);      // a tap leaves scrolling to the browser
    return (this.gesture = { kind, id: e.pointerId, page: i, start: pt, cur: pt, x: e.clientX, y: e.clientY, moved: false });
  }

  private move(e: PointerEvent) {
    const g = this.gesture;
    if (!g || g.id !== e.pointerId) return;
    if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < (e.pointerType === "mouse" ? 3 : 6)) return;
    g.moved = true;
    if (g.kind === "pan") {
      this.el.scrollBy(g.x - e.clientX, g.y - e.clientY);
      [g.x, g.y] = [e.clientX, e.clientY];
      return;
    }
    g.cur = this.toPage(g.page, e);
    if (g.kind === "ink") g.stroke!.push(g.cur);
    if ((g.kind === "move" || g.kind === "resize") && this.selBox && this.selected) {
      Object.assign(this.selBox.style, this.percent(g.page, this.dragged(g)));
      this.hideBar();
    } else this.paint(g.page);
  }

  /** The selected comment's box as the drag in progress leaves it. */
  private dragged(g: Gesture): Rect {
    const r = this.selected!.comment.rect, dx = g.cur[0] - g.start[0], dy = g.cur[1] - g.start[1];
    if (g.kind === "move") return [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy];
    const c = g.corner!;
    const out: Rect = [c.includes("w") ? r[0] + dx : r[0], c.includes("n") ? r[1] + dy : r[1], c.includes("e") ? r[2] + dx : r[2], c.includes("s") ? r[3] + dy : r[3]];
    return norm([out[0], out[1]], [out[2], out[3]]);
  }

  private up(e: PointerEvent) {
    const g = this.gesture;
    if (!g || g.id !== e.pointerId) return;
    this.gesture = null;
    const page = g.page + 1, tool = this.tool;
    if (g.kind === "tap" || g.kind === "pan") {
      if (!g.moved) this.tap(g.page, g.start);
    } else if (g.kind === "move" || g.kind === "resize") {
      const c = this.selected!.comment;
      if (!g.moved) return this.onselect();
      if (g.kind === "move") this.onaction({ tool: "move-comment", page, xref: c.xref, dx: g.cur[0] - g.start[0], dy: g.cur[1] - g.start[1] });
      else this.onaction({ tool: "resize-comment", page, xref: c.xref, rect: this.dragged(g) });
    } else if (g.kind === "text") {
      const lines = g.moved && g.words ? textBetween(g.words, g.start, g.cur) : [];
      if (tool === "select") {
        this.textSel = lines.length ? { page: g.page, start: g.start, stop: g.cur, lines } : null;
        if (!lines.length) this.tap(g.page, g.start);
        this.paint(g.page);
        this.onselect();
      } else if (lines.length) this.onaction({ tool, page, start: g.start, stop: g.cur });
      else if (g.moved || !g.words?.length) this.onaction({ tool: "no-text", page });
    } else if (g.kind === "rect") {
      const r = norm(g.start, g.cur);
      if (g.moved && r[2] - r[0] > 3 && r[3] - r[1] > 3) this.onaction({ tool, page, rect: r });
      else this.onaction({ tool, page, point: g.start });
    } else if (g.kind === "line") {
      if (g.moved) this.onaction({ tool, page, p1: g.start, p2: g.cur });
    } else if (g.kind === "ink") {
      if (g.stroke!.length === 1) g.stroke!.push([g.start[0] + 0.5, g.start[1] + 0.5]);       // a dot
      (this.ink ??= { page: g.page, strokes: [] }).strokes.push(g.stroke!);
      this.inkTimer = window.setTimeout(() => this.flushInk(), 1100);       // strokes close together are one drawing
    } else if (g.kind === "point") this.onaction({ tool, page, point: g.start });
    if (g.kind !== "ink" && g.kind !== "move" && g.kind !== "resize") this.paint(g.page);
  }

  private cancel() {
    const g = this.gesture;
    this.gesture = null;
    if (!g) return;
    if (this.selBox && this.selected) Object.assign(this.selBox.style, this.percent(g.page, this.selected.comment.rect));
    this.paint(g.page);
  }

  /** Hand the pencil strokes drawn so far to the app as one comment. */
  flushInk() {
    clearTimeout(this.inkTimer);
    const ink = this.ink;
    if (!ink) return;
    this.ink = null;
    const sent = (this.sent = { ...ink, rev: this.doc?.pages[ink.page]?.rev ?? 0 });      // stays drawn until the page is
    setTimeout(() => {
      if (this.sent !== sent) return;
      this.sent = null;
      this.paint(sent.page);
    }, 5000);
    this.onaction({ tool: "pencil", page: ink.page + 1, strokes: ink.strokes });
  }

  private async tap(i: number, pt: Pt) {
    const doc = this.doc!;
    this.clearTextSel();
    let items: Items;
    try {
      items = await doc.itemsOf(i);
    } catch {
      return;
    }
    if (this.doc !== doc) return;
    const field = items.fields.find((f) => inside(f.rect, pt));
    if (field) {
      this.select(null);
      return this.onaction({ tool: "field", page: i + 1, field });
    }
    const area = (c: Comment) => (c.rect[2] - c.rect[0]) * (c.rect[3] - c.rect[1]);
    const comment = items.comments.filter((c) => inside(c.rect, pt, 3)).sort((a, b) => area(a) - area(b))[0];
    if (comment) return this.select({ page: i, comment });
    this.select(null);
    const link = items.links.find((l) => inside(l.rect, pt));
    if (link?.page != null) this.goto(link.page, link.y ?? 0);
    else if (link?.uri) this.onaction({ tool: "open-url", page: i + 1, url: link.uri });
  }

  // ---- pinch ------------------------------------------------------------------------------------------
  private touch(e: TouchEvent) {
    const t = e.touches;
    if (t.length !== 2) {
      if (this.pinch) {
        this.pinch = null;
        this.fit = null;
      }
      return;
    }
    const r = this.el.getBoundingClientRect();
    const x = (t[0].clientX + t[1].clientX) / 2 - r.left, y = (t[0].clientY + t[1].clientY) / 2 - r.top;
    const d = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
    if (!this.pinch) {
      this.cancel();
      if (!this.doc?.pages.length) return;
      this.pinch = { d0: d, z0: this.zoom, at: this.locate(x, y) };
    } else if (e.type === "touchmove") {
      this.zoomAt(this.pinch.z0 * (d / this.pinch.d0), this.pinch.at, x, y);      // what was under the fingers stays there
    }
    if (e.cancelable) e.preventDefault();
  }

  // ---- selection ----------------------------------------------------------------------------------------
  select(sel: { page: number; comment: Comment } | null) {
    this.selBox?.remove();
    this.selBox = null;
    this.hideBar();
    this.selected = sel;
    if (sel && this.views[sel.page]) {
      const corners = sel.comment.resizable ? ["nw", "ne", "sw", "se"].map((c) => { const el = h("i", { class: "grip " + c }); el.dataset.corner = c; return el; }) : [];
      this.selBox = h("div", { class: "sel", style: this.percent(sel.page, sel.comment.rect) }, ...corners);
      this.views[sel.page].el.append(this.selBox);
    }
    this.onselect();
  }

  clearTextSel() {
    const sel = this.textSel;
    if (!sel) return;
    this.textSel = null;
    this.paint(sel.page);
    this.hideBar();
  }

  selectedText(): string {
    return this.textSel ? this.textSel.lines.map((l) => l.text).join("\n") : "";
  }

  /** A row of actions next to what is selected, kept inside the part of the page that is in view. */
  showBar(i: number, rect: Rect, buttons: BarButton[]) {
    this.hideBar();
    const p = this.doc!.pages[i], r = applyRect(p.m, rect), z = this.zoom;
    const above = r[1] * z + this.top(i) - this.el.scrollTop > 64;
    this.bar = h("div", { class: "bar" + (above ? "" : " below") },
      ...buttons.map((b) => h("button", { type: "button", class: b.danger ? "danger" : "", onclick: () => b.run() }, b.label)));
    this.views[i].el.append(this.bar);
    const half = this.bar.offsetWidth / 2, from = this.el.scrollLeft - this.left(i);
    const x = Math.max(from + half + 8, Math.min(from + this.el.clientWidth - half - 8, ((r[0] + r[2]) / 2) * z));
    Object.assign(this.bar.style, { left: `${x}px`, top: `${(above ? r[1] : r[3]) * z}px` });
  }

  hideBar() {
    this.bar?.remove();
    this.bar = null;
  }

  // ---- search hits ------------------------------------------------------------------------------------
  setHits(found: [number, Rect[]][]) {
    const old = new Set(this.hits.map((x) => x.page));
    this.hits = found.flatMap(([page, rects]) => rects.map((rect) => ({ page, rect })));
    this.hit = -1;
    for (const i of new Set([...old, ...this.hits.map((x) => x.page)])) this.paint(i);
  }

  showHit(k: number) {
    if (!this.hits.length) return;
    const before = this.hits[this.hit]?.page;
    this.hit = (k + this.hits.length) % this.hits.length;
    const hit = this.hits[this.hit];
    if (before != null) this.paint(before);
    this.paint(hit.page);
    if (this.top(hit.page) + this.doc!.pages[hit.page].h * this.zoom < this.el.scrollTop || this.top(hit.page) > this.el.scrollTop + this.el.clientHeight) this.goto(hit.page);
    this.reveal(hit.page, hit.rect);
  }

  // ---- typing on the page -----------------------------------------------------------------------------
  /** An editor on the page at `rect` (text starts at its top-left). Resolves with the text, or null if given up. */
  edit(i: number, rect: Rect, opts: { value?: string; fontsize: number; color?: string; multiline?: boolean; fixed?: boolean; grow?: boolean; options?: string[] } = { fontsize: 12 }): Promise<string | null> {
    this.closeEditor(true);
    return new Promise((resolve) => {
      const pos = this.percent(i, rect);
      const font = { fontSize: `calc(var(--z) * ${opts.fontsize}px)`, color: opts.color ?? "#000" };
      let input: HTMLTextAreaElement | HTMLInputElement | HTMLSelectElement;
      if (opts.options?.length) {
        input = h("select", { style: font }, h("option", { value: "" }, ""), ...opts.options.map((o) => h("option", { value: o, selected: o === opts.value }, o)));
      } else if (opts.multiline) {
        input = h("textarea", { value: opts.value ?? "", style: font, rows: 1, spellcheck: false });
      } else {
        input = h("input", { type: "text", value: opts.value ?? "", style: font, spellcheck: false, enterKeyHint: "done" });
      }
      const ok = h("button", { type: "button", class: "editor-ok", "aria-label": "OK" }, "✓");
      const el = h("div", { class: "editor" + (opts.fixed ? " fixed" : ""), style: opts.fixed ? pos : { left: pos.left, top: pos.top } }, input, ok);
      const grow = () => {
        if (opts.grow) input.style.minWidth = `calc(${input.value.length + 2}ch)`;        // a line being edited may get longer than its box
        if (!(input instanceof HTMLTextAreaElement) || opts.fixed) return;
        input.style.height = "auto";
        input.style.height = input.scrollHeight + "px";
        input.style.width = "auto";
        const longest = Math.max(4, ...input.value.split("\n").map((s) => s.length));
        input.style.width = `calc(${longest + 2}ch + 8px)`;
      };
      let finished = false;
      const done = (commit: boolean) => {
        if (finished) return;
        finished = true;
        this.editor = null;
        el.remove();
        resolve(commit ? input.value : null);
      };
      input.addEventListener("input", grow);
      input.addEventListener("keydown", (e) => {
        const ev = e as KeyboardEvent;
        if (ev.key === "Escape") done(false);
        else if (ev.key === "Enter" && (!opts.multiline || ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); done(true); }
        ev.stopPropagation();
      });
      if (input instanceof HTMLSelectElement) input.addEventListener("change", () => done(true));
      input.addEventListener("blur", () => setTimeout(() => done(true), 120));         // a tap on ✓ arrives first
      ok.addEventListener("pointerdown", (e) => { e.preventDefault(); done(true); });
      this.views[i].el.append(el);
      this.editor = { el, done };
      grow();
      input.focus({ preventScroll: false });
      if (!(input instanceof HTMLSelectElement)) input.setSelectionRange(input.value.length, input.value.length);
    });
  }

  closeEditor(commit: boolean) {
    this.editor?.done(commit);
  }
}
