// The open document as the interface sees it: page sizes, what was edited, and per-page data kept until
// the next edit. Every change goes through run(), which is one undo step on the Python side.
import { call, type Upload } from "./engine";

export type Pt = [number, number];
export type Rect = [number, number, number, number];
export type Matrix = number[];
export type Page = { w: number; h: number; rotation: number; m: Matrix; inv: Matrix; rev: number };
export type Word = [number, number, number, number, string, number, number];
export type Comment = { xref: number; type: string; kind: string; rect: Rect; content: string; author: string; color: number[]; resizable: boolean };
export type FormField = { xref: number; type: string; rect: Rect; name: string; label: string; value: any; options: string[]; readonly: boolean; multiline: boolean; fontsize: number };
export type Link = { rect: Rect; page?: number; y?: number; uri?: string };
export type Items = { comments: Comment[]; fields: FormField[]; links: Link[] };

export const apply = (m: Matrix, p: Pt): Pt => [m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5]];

export function invert(m: Matrix): Matrix {
  const det = m[0] * m[3] - m[1] * m[2];
  return [m[3] / det, -m[1] / det, -m[2] / det, m[0] / det, (m[2] * m[5] - m[3] * m[4]) / det, (m[1] * m[4] - m[0] * m[5]) / det];
}

export function applyRect(m: Matrix, r: Rect): Rect {
  const a = apply(m, [r[0], r[1]]), b = apply(m, [r[2], r[3]]);
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}

export const inside = (r: Rect, p: Pt, pad = 0) => p[0] >= r[0] - pad && p[0] <= r[2] + pad && p[1] >= r[1] - pad && p[1] <= r[3] + pad;

export class Doc {
  id = 0;
  name = "";
  pages: Page[] = [];
  modified = false;
  readonly = false;
  protected = false;
  form = false;
  signed = false;
  bookmarks = 0;
  undoLabel: string | null = null;
  redoLabel: string | null = null;
  handle?: FileSystemFileHandle;                // where Save writes, in browsers that give one
  onchange: (pagesChanged: boolean) => void = () => {};
  private words = new Map<number, Promise<Word[]>>();
  private items = new Map<number, Promise<Items>>();
  private rev = 0;

  constructor(info: any) {
    this.take(info);
  }

  private take(info: any) {
    this.id = info.id;
    this.name = info.name;
    this.modified = info.modified;
    this.readonly = info.readonly;
    this.protected = info.protected;
    this.undoLabel = info.undo;
    this.redoLabel = info.redo;
    if (info.pages) {
      this.form = info.form;
      this.signed = info.signed;
      this.bookmarks = info.bookmarks;
      this.rev++;
      this.pages = info.pages.map((p: number[]) => ({ w: p[0], h: p[1], rotation: p[2], m: p.slice(3), inv: invert(p.slice(3)), rev: this.rev }));
    }
  }

  /** Read the document's state again. `pages`: the only pages (0-based) whose look changed; none given = all. */
  async refresh(pages?: number[]) {
    if (pages) {
      this.take(await call("state", { sid: this.id }));
      this.rev++;
      for (const i of pages) {
        if (this.pages[i]) this.pages[i].rev = this.rev;
        this.words.delete(i);
        this.items.delete(i);
      }
    } else {
      this.take(await call("info", { sid: this.id }));
      this.words.clear();
      this.items.clear();
    }
    this.onchange(!pages);
  }

  /** Run a command as one undo step. `pages` as in refresh. */
  async run<T = any>(name: string, args: object, opts: { label?: string; pages?: number[]; files?: Upload[] } = {}): Promise<T> {
    try {
      return await call<T>("run", { sid: this.id, name, args, label: opts.label ?? name }, opts.files);
    } finally {
      await this.refresh(opts.pages);
    }
  }

  query<T = any>(name: string, args: object = {}): Promise<T> {
    return call<T>("query", { sid: this.id, name, args });
  }

  async undo(redo = false): Promise<string | null> {
    const label = await call<string | null>(redo ? "redo" : "undo", { sid: this.id });
    await this.refresh();
    return label;
  }

  wordsOf(i: number): Promise<Word[]> {
    if (!this.words.has(i)) this.words.set(i, call("words", { sid: this.id, page: i }));
    return this.words.get(i)!;
  }

  itemsOf(i: number): Promise<Items> {
    if (!this.items.has(i)) this.items.set(i, call("page_items", { sid: this.id, page: i }));
    return this.items.get(i)!;
  }
}

/** The text flow between two points, as pdfdesk.commands.comment.text_between gives it: line boxes and text. */
export function textBetween(words: Word[], start: Pt, stop: Pt): { rect: Rect; text: string }[] {
  if (!words.length) return [];
  const gap = (lo: number, hi: number, v: number) => Math.max(lo - v, 0, v - hi);
  const nearest = (pt: Pt) => {
    let best = -1, score = Infinity;
    const same = words.some((w) => w[1] - 2 <= pt[1] && pt[1] <= w[3] + 2);
    words.forEach((w, k) => {
      if (same && !(w[1] - 2 <= pt[1] && pt[1] <= w[3] + 2)) return;
      const s = same ? gap(w[0], w[2], pt[0]) : gap(w[1], w[3], pt[1]) * 4 + gap(w[0], w[2], pt[0]);
      if (s < score) [best, score] = [k, s];
    });
    return best;
  };
  const [a, b] = [nearest(start), nearest(stop)].sort((x, y) => x - y);
  const out: { rect: Rect; text: string }[] = [];
  let key = "";
  for (const w of words.slice(a, b + 1)) {
    if (`${w[5]}:${w[6]}` !== key) {
      key = `${w[5]}:${w[6]}`;
      out.push({ rect: [w[0], w[1], w[2], w[3]], text: w[4] });
    } else {
      const last = out[out.length - 1];
      last.rect = [Math.min(last.rect[0], w[0]), Math.min(last.rect[1], w[1]), Math.max(last.rect[2], w[2]), Math.max(last.rect[3], w[3])];
      last.text += " " + w[4];
    }
  }
  return out;
}
