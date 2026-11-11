// tr() as in the desktop app: the English text is the key, and the German and Arabic tables are the same ones
// (pdfdesk/lang/), read from the Python side. tests/test_lang.py checks the strings used here against them.
import { call } from "./engine";

export const LANGUAGES: [string, string][] = [["en", "English"], ["de", "Deutsch"], ["ar", "العربية"]];
let table: Record<string, string> = {};
let code = "en";

export function tr(text: string, values?: Record<string, string | number>): string {
  const s = table[text] ?? text;
  return values ? s.replace(/\{(\w+)\}/g, (m, k) => (k in values ? String(values[k]) : m)) : s;
}

export const language = () => code;

export function preferred(): string {
  let saved: string | null = null;
  try {
    saved = localStorage.getItem("pdfdesk.language");
  } catch { /* private mode */ }
  const want = saved ?? navigator.language.slice(0, 2);
  return LANGUAGES.some(([c]) => c === want) ? want : "en";
}

export async function setLanguage(want: string) {
  const res = await call("strings", { code: want });
  table = res.table;
  code = res.code;
  document.documentElement.lang = code;
  document.documentElement.dir = res.rtl ? "rtl" : "ltr";
  try {
    localStorage.setItem("pdfdesk.language", code);
  } catch { /* private mode */ }
}
