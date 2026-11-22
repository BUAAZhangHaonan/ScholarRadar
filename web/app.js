import { $, esc, msg, showEvidence } from "./common.js";

const path = location.pathname;
const routes = {
  "/": "daily",
  "/directions": "directions",
  "/library": "library",
  "/tasks": "tasks",
  "/actions": "tasks",
  "/settings": "settings",
  "/maintenance": "maintenance",
};
const moduleName =
  routes[path] ||
  (path.startsWith("/directions/")
    ? "directions"
    : path.startsWith("/works/")
      ? "library"
      : path.startsWith("/tasks/")
        ? "tasks"
        : null);
const navPath = {
  daily: "/",
  directions: "/directions",
  library: "/library",
  tasks: "/tasks",
  settings: "/settings",
  maintenance: "/maintenance",
}[moduleName];
for (const a of document.querySelectorAll(".mast a,.foot-inner a"))
  if (a.pathname === navPath && !a.classList.contains("brand"))
    a.setAttribute("aria-current", "page");
$("#close").onclick = () => $("#detail").close();
$("#evidence-close").onclick = () => $("#evidence-drawer").close();
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-evidence]");
  if (b) {
    const ids = b.closest("[data-evidence-set]")?.dataset.evidenceSet.split(" ") || [];
    showEvidence(b.dataset.evidence, ids, b).catch((x) => msg(x.message));
  }
});

function expansionState() {
  return [...document.querySelectorAll("main details")].map((el, i) => ({
    key: el.id || i + ":" + el.querySelector("summary")?.textContent,
    open: el.open,
  }));
}
window.addEventListener("pagehide", () => {
  const view = {
    x: scrollX,
    y: scrollY,
    expanded: expansionState()
      .filter((x) => x.open)
      .map((x) => x.key),
  };
  history.replaceState({ ...history.state, radarView: view }, "");
});
function restore() {
  const saved = history.state?.radarView;
  if (saved) {
    const keys = new Set(saved.expanded || []);
    document
      .querySelectorAll("main details")
      .forEach(
        (el, i) =>
          (el.open = keys.has(
            el.id || i + ":" + el.querySelector("summary")?.textContent,
          )),
      );
    requestAnimationFrame(() => scrollTo(saved.x, saved.y));
  } else if (location.hash) {
    const target = document.getElementById(
      decodeURIComponent(location.hash.slice(1)),
    );
    if (target) {
      if (target.matches("details")) target.open = true;
      requestAnimationFrame(() => target.scrollIntoView());
    }
  }
}
try {
  if (!moduleName) throw Error("页面不存在");
  const mod = await import("./" + moduleName + ".js");
  await mod.render();
  restore();
} catch (err) {
  $("#app").innerHTML = '<p class="error">' + esc(err.message) + "</p>";
}
