// Start: Python first (the commands and the translations live there), then the window.
import "./style.css";
import { h } from "./dom";
import { call, start } from "./engine";
import { preferred, setLanguage, tr } from "./i18n";
import { onIncoming, native, type Picked } from "./platform";

const splash = document.getElementById("splash")!;
const waiting: Picked[] = [];
let open: (f: Picked) => void = (f) => waiting.push(f);
onIncoming((f) => open(f));                       // a file the app was started with can arrive before it is ready

/** The app stays shut until the product key was entered once; it is then kept on this device. */
async function unlock() {
  const stored = () => { try { return localStorage.getItem("pdfdesk.key") ?? ""; } catch { return ""; } };
  if (await call<boolean>("activate", { key: stored() })) return;
  await new Promise<void>((done) => {
    const input = h("input", { type: "text", autocomplete: "off", autocapitalize: "characters", spellcheck: false, "aria-label": tr("Product Key") });
    const wrong = h("p", { class: "key-wrong", role: "alert" });
    const gate = h("form", { class: "key-gate", onsubmit: async (e: Event) => {
      e.preventDefault();
      if (!(await call<boolean>("activate", { key: input.value }))) return void (wrong.textContent = tr("This product key is not valid."));
      try { localStorage.setItem("pdfdesk.key", input.value.trim()); } catch { /* asked again next time */ }
      gate.remove();
      spinner?.removeAttribute("hidden");
      done();
    } }, h("p", null, tr("Enter the product key to use pdfdesk.")), input, wrong, h("button", { type: "submit", class: "btn primary" }, tr("Activate")));
    const spinner = splash.querySelector(".spinner");
    spinner?.setAttribute("hidden", "");
    splash.append(gate);
    input.focus();
  });
}

try {
  await start(() => {});
  await setLanguage(preferred());
  await unlock();
  const app = await import("./app");
  splash.remove();
  await app.init(waiting, (fn) => (open = fn));
  if ("serviceWorker" in navigator && !native && import.meta.env.PROD) navigator.serviceWorker.register("./sw.js").catch(() => {});
} catch (e) {
  splash.querySelector(".spinner")?.remove();
  splash.querySelector("p")!.textContent = "pdfdesk could not start on this device: " + String((e as Error)?.message ?? e);
}
