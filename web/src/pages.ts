// The Pages sheet: thumbnails to pick pages from, and what can be done with the picked ones.
import type { Doc } from "./doc";
import { button, h, sheet } from "./dom";
import { call } from "./engine";
import { tr } from "./i18n";

export type PageOps = {
  rotate(pages: string, angle: number): Promise<void>;
  remove(pages: string): Promise<void>;
  extract(pages: string): Promise<void>;
  move(page: number, before: number): Promise<void>;
  insertBlank(after: number): Promise<void>;
  insertFile(after: number): Promise<void>;
  goto(page: number): void;
};

/** "1-3,7" for a set of 0-based page indexes. */
export function range(picked: Iterable<number>): string {
  const s = [...picked].sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < s.length; i++) {
    let j = i;
    while (j + 1 < s.length && s[j + 1] === s[j] + 1) j++;
    out.push(i === j ? `${s[i] + 1}` : `${s[i] + 1}-${s[j] + 1}`);
    i = j;
  }
  return out.join(",");
}

export function show(doc: Doc, current: number, ops: PageOps) {
  const picked = new Set<number>([current]);
  const grid = h("div", { class: "thumbs" });
  const count = h("span", { class: "hint" });
  let closed = false;
  const watcher = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) draw(e.target as HTMLElement);
  }, { root: null, rootMargin: "200px" });

  async function draw(cell: HTMLElement) {
    watcher.unobserve(cell);
    const i = Number(cell.dataset.page), p = doc.pages[i];
    if (!p) return;
    try {
      const { meta, data } = await call("render", { sid: doc.id, page: i, scale: 150 / Math.max(p.w, p.h) * (window.devicePixelRatio > 1 ? 2 : 1) });
      if (closed) return;
      const canvas = cell.querySelector("canvas")!;
      canvas.width = meta.width;
      canvas.height = meta.height;
      canvas.getContext("2d")!.putImageData(new ImageData(new Uint8ClampedArray(data.buffer as ArrayBuffer), meta.width, meta.height), 0, 0);
    } catch { /* a page that cannot be drawn stays blank */ }
  }

  function mark() {
    for (const cell of grid.children) cell.classList.toggle("on", picked.has(Number((cell as HTMLElement).dataset.page)));
    count.textContent = picked.size ? tr("Pages: {pages}", { pages: range(picked) }) : tr("Tap pages to choose them");
    for (const b of bar.querySelectorAll<HTMLButtonElement>("button[data-needs]")) {
      const need = b.dataset.needs!;
      b.disabled = need === "one" ? picked.size !== 1 : need === "some" ? !picked.size || (b.dataset.keep === "1" && picked.size >= doc.pages.length) : false;
    }
  }

  function build() {
    watcher.disconnect();
    for (const i of [...picked]) if (i >= doc.pages.length) picked.delete(i);
    grid.replaceChildren(...doc.pages.map((p, i) => {
      const cell = h("button", { type: "button", class: "thumb", onclick: () => { picked.has(i) ? picked.delete(i) : picked.add(i); mark(); } },
        h("canvas", { style: { aspectRatio: `${p.w} / ${p.h}` } }), h("span", null, String(i + 1)));
      cell.dataset.page = String(i);
      watcher.observe(cell);
      return cell;
    }));
    mark();
  }

  const act = (needs: string, label: string, icon: string, run: () => Promise<unknown> | void, keep = false) => {
    const b = button(label, async () => { await run(); if (!closed) build(); }, { icon });
    b.dataset.needs = needs;
    if (keep) b.dataset.keep = "1";
    return b;
  };
  const one = () => [...picked][0];
  const repick = (i: number) => { picked.clear(); picked.add(Math.max(0, Math.min(doc.pages.length - 1, i))); };
  const bar = h("div", { class: "thumb-actions" },
    act("one", tr("Go to"), "next", () => { ops.goto(one()); s.close(); }),
    act("some", tr("Rotate Left"), "rotate-l", () => ops.rotate(range(picked), -90)),
    act("some", tr("Rotate Right"), "rotate-r", () => ops.rotate(range(picked), 90)),
    act("one", tr("Move Up"), "up", async () => { const i = one(); if (i > 0) { await ops.move(i + 1, i); repick(i - 1); } }),
    act("one", tr("Move Down"), "down", async () => { const i = one(); if (i < doc.pages.length - 1) { await ops.move(i + 1, i + 3); repick(i + 1); } }),
    act("some", tr("Extract"), "extract", () => ops.extract(range(picked))),
    act("some", tr("Delete"), "delete", async () => { await ops.remove(range(picked)); picked.clear(); }, true),
    act("any", tr("Insert Blank"), "insert", () => ops.insertBlank(picked.size ? Math.max(...picked) + 1 : doc.pages.length)),
    act("any", tr("Insert File"), "insert-file", () => ops.insertFile(picked.size ? Math.max(...picked) + 1 : doc.pages.length)),
  );
  const s = sheet(tr("Pages"), [bar, count, grid], { wide: true, onClose: () => { closed = true; watcher.disconnect(); } });
  build();
  grid.querySelector(".thumb.on")?.scrollIntoView({ block: "center" });
}
