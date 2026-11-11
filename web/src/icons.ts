// Icons drawn here (no image files), 24 px line icons in the text colour; a few carry the colour of what they do.
const P = (d: string, extra = "") => `<path d="${d}" ${extra}/>`;
const YELLOW = "#f1c40f", RED = "#d33a3a", GREEN = "#2e9e5b", BLUE = "#2b6cc4";
const page = "M6 3h8l4 4v14H6z M14 3v4h4";
const lens = `<circle cx="11" cy="11" r="6"/>` + P("M20 20l-4.6-4.6");
const A = "M8 14l4-10 4 10 M9.4 10.5h5.2";

const ICONS: Record<string, string> = {
  menu: P("M4 6h16 M4 12h16 M4 18h16"),
  more: `<circle cx="12" cy="5" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="12" cy="19" r="1.3"/>`,
  close: P("M6 6l12 12 M18 6L6 18"),
  check: P("M5 12.5l4.5 4.5L19 7"),
  plus: P("M12 5v14 M5 12h14"),
  up: P("M6 15l6-6 6 6"),
  down: P("M6 9l6 6 6-6"),
  prev: P("M15 6l-6 6 6 6"),
  next: P("M9 6l6 6-6 6"),
  open: P("M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"),
  save: P("M5 3h11l4 4v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M7 3v6h8V3 M7 21v-7h10v7"),
  share: P("M12 15V3 M8 7l4-4 4 4 M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"),
  print: P("M7 8V3h10v5 M7 17H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2 M7 14h10v7H7z"),
  undo: P("M9 5L4 10l5 5 M4 10h10a6 6 0 0 1 0 12h-3"),
  redo: P("M15 5l5 5-5 5 M20 10H10a6 6 0 0 0 0 12h3"),
  search: lens,
  "zoom-in": lens + P("M11 8.5v5 M8.5 11h5"),
  "zoom-out": lens + P("M8.5 11h5"),
  "fit-width": P("M3 12h18 M7 8l-4 4 4 4 M17 8l4 4-4 4"),
  "fit-page": P("M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5"),
  hand: P("M8 13V5.5a1.5 1.5 0 0 1 3 0V11 M11 11V4.5a1.5 1.5 0 0 1 3 0V11 M14 11V6a1.5 1.5 0 0 1 3 0v6 M17 12V9.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-2a6 6 0 0 1-5-2.7L4.6 14.2A1.5 1.5 0 0 1 7 12.5l1 1.5"),
  select: P("M8 4c2 0 4 .5 4 2 0-1.5 2-2 4-2 M8 20c2 0 4-.5 4-2 0 1.5 2 2 4 2 M12 6v12 M10 12h4"),
  pages: `<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>`,
  bookmarks: P("M7 3h10v18l-5-4-5 4z"),
  comments: P("M4 5h16v11H10l-5 4v-4H4z"),
  highlight: `<rect x="3" y="15" width="18" height="6" rx="1" fill="${YELLOW}" stroke="none"/>` + P(A),
  underline: P(A) + P("M5 19h14", `stroke="${GREEN}" stroke-width="2.4"`),
  strikeout: P(A) + P("M4 10.5h16", `stroke="${RED}" stroke-width="2.2"`),
  squiggly: P(A) + P("M4 19c2-3 3 3 5.3 0s3.3 3 5.4 0 3.3 3 5.3 0", `stroke="${BLUE}" stroke-width="2"`),
  note: P("M5 4h14v11l-5 5H5z M14 20v-5h5"),
  typewriter: P("M4 6V5h10v1 M9 5v14 M7 19h4 M17 9v10 M15 9h4 M15 19h4"),
  textbox: `<rect x="3" y="5" width="18" height="14" rx="1.5"/>` + P("M9 9h6 M12 9v6.5"),
  pencil: P("M4 20l1-4.5L16.5 4l3.5 3.5L8.5 19z M14 6.5l3.5 3.5"),
  rectangle: `<rect x="4" y="6" width="16" height="12" rx="1"/>`,
  oval: `<ellipse cx="12" cy="12" rx="8.5" ry="6"/>`,
  line: P("M5 19L19 5"),
  arrow: P("M5 19L19 5 M11 5h8v8"),
  "area-highlight": `<rect x="4" y="6" width="16" height="12" rx="1" fill="${YELLOW}" fill-opacity=".55" stroke-dasharray="3 2.5"/>`,
  stamp: P("M9.5 3h5v5.5l2.5 3.5v3H7v-3l2.5-3.5z M5 20h14"),
  color: P("M12 3s6 6.6 6 11a6 6 0 0 1-12 0c0-4.4 6-11 6-11z"),
  "add-text": P("M4 6V5h10v1 M9 5v14 M7 19h4 M18 12v7 M14.5 15.5h7"),
  sign: P("M3 16c3-7 5-7 5-2.5s2 3 4-1 3 3.5 6 1 M3 20.5h18"),
  image: `<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="9.5" r="1.4"/>` + P("M3.5 16.5l4.5-4.5 4 4 3-3 5.5 5.5"),
  flatten: P("M12 4l9 5-9 5-9-5z M3 14l9 5 9-5"),
  reset: P("M4.5 12a7.5 7.5 0 1 0 2.5-5.6 M4 4v5h5"),
  "edit-text": P("M4 6V5h10v1 M9 5v14 M7 19h4 M14.5 20l.8-3.2 4.2-4.2 2.4 2.4-4.2 4.2z"),
  replace: P("M4 8h14 M15 5l3 3-3 3 M20 16H6 M9 13l-3 3 3 3"),
  link: P("M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"),
  "rotate-r": P("M19.5 12a7.5 7.5 0 1 1-2.5-5.6 M20 4v5h-5"),
  "rotate-l": P("M4.5 12a7.5 7.5 0 1 0 2.5-5.6 M4 4v5h5"),
  delete: P("M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v6 M14 11v6"),
  extract: P("M12 21H6V3h8l4 4v5 M14 3v4h4 M14 18h7 M18 15l3 3-3 3"),
  insert: P(page + " M12 11v6 M9 14h6"),
  "insert-file": P("M9 3h6l4 4v10H9z M15 3v4h4 M5 7v14h10"),
  reverse: P("M7 4v16 M4 7l3-3 3 3 M17 20V4 M14 17l3 3 3-3"),
  split: P("M4 5h6v14H4z M14 5h6v14h-6z") + P("M12 3v18", `stroke-dasharray="2.5 2.5"`),
  crop: P("M7 3v14h14 M3 7h14v14"),
  header: P(page) + P("M9 11h6", `stroke="${BLUE}" stroke-width="2.2"`),
  watermark: P(page) + P("M9 18l6-6", `stroke-width="2.2" stroke-opacity=".45"`),
  background: `<path d="M6 3h8l4 4v14H6z" fill="${YELLOW}" fill-opacity=".45"/>` + P("M14 3v4h4"),
  redact: `<rect x="3" y="9" width="18" height="6" rx="1" fill="currentColor"/>`,
  whiteout: `<rect x="3" y="9" width="18" height="6" rx="1"/>`,
  apply: `<rect x="3" y="14" width="18" height="6" rx="1" fill="currentColor"/>` + P("M7 8l3 3 6-7"),
  "search-redact": `<circle cx="10" cy="10" r="5.5"/>` + P("M19 19l-4.8-4.8") + `<rect x="7" y="8.6" width="6" height="2.8" fill="currentColor" stroke="none"/>`,
  password: `<rect x="5" y="11" width="14" height="10" rx="2"/>` + P("M8 11V8a4 4 0 0 1 8 0v3"),
  unlock: `<rect x="5" y="11" width="14" height="10" rx="2"/>` + P("M8 11V8a4 4 0 0 1 7.6-1.7"),
  hidden: P("M3 3l18 18 M10.5 6.2A9.5 9.5 0 0 1 21 12a13 13 0 0 1-2.2 3 M6.5 7.5A13 13 0 0 0 3 12a9.6 9.6 0 0 0 12 5.3 M9.9 9.9a3 3 0 0 0 4.2 4.2"),
  create: P(page + " M12 11v6 M9 14h6"),
  combine: P("M4 4h7v7H4z M13 13h7v7h-7z M11 7.5h4a2 2 0 0 1 2 2V13"),
  text: P("M5 6h14 M5 10h14 M5 14h10 M5 18h7"),
  html: P("M8 7l-5 5 5 5 M16 7l5 5-5 5 M13.5 5l-3 14"),
  excel: `<rect x="3" y="4" width="18" height="16" rx="1.5"/>` + P("M3 9.5h18 M3 14.5h18 M9 4v16"),
  optimize: P("M12 3v9 M8 8.5l4 4 4-4 M5 16h14 M5 20h14"),
  language: `<circle cx="12" cy="12" r="9"/>` + P("M3 12h18 M12 3a14 14 0 0 1 0 18 M12 3a14 14 0 0 0 0 18"),
  about: `<circle cx="12" cy="12" r="9"/>` + P("M12 11v6 M12 7.5v.2"),
  invoice: P("M6 3h12v18l-3-2-3 2-3-2-3 2z M9 8h6 M9 12h6"),
};

export function icon(name: string): SVGElement {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  el.setAttribute("viewBox", "0 0 24 24");
  el.setAttribute("class", "icon");
  el.setAttribute("aria-hidden", "true");
  el.innerHTML = ICONS[name] ?? ICONS.about;
  return el;
}
