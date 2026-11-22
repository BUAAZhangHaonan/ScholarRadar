import { esc } from "./common.js";

let dispose;
export function mountReadingOutline(article, prefix) {
  dispose?.();
  dispose = undefined;
  const targets = [...article.querySelectorAll("[data-reading-part]")];
  if (targets.length < 3) return;

  const used = new Set();
  const entries = targets.map((target) => {
    const base = prefix + "-" + target.dataset.readingPart;
    let id = base, n = 1;
    while (used.has(id)) id = base + "-" + ++n;
    used.add(id);
    target.id = id;
    if (!target.matches("summary")) target.tabIndex = -1;
    return { id, target, label: target.dataset.readingLabel || target.textContent.trim() };
  });

  const layout = document.createElement("div");
  layout.className = "reader-spread";
  const nav = document.createElement("nav");
  nav.className = "reading-outline";
  nav.setAttribute("aria-label", "阅读目录");
  nav.innerHTML = '<details><summary>阅读目录</summary><ul>' + entries.map(({ id, label }) =>
    '<li><a href="#' + esc(id) + '">' + esc(label) + '</a></li>'
  ).join("") + '</ul></details>';
  article.before(layout);
  layout.append(nav, article);
  article.classList.add("reader-column");

  const wide = matchMedia("(min-width: 980px)");
  const panel = nav.querySelector("details");
  panel.open = wide.matches;
  const links = [...nav.querySelectorAll("a")];
  function expose(target) {
    for (let fold = target.closest("details"); fold && article.contains(fold); fold = fold.parentElement?.closest("details")) {
      fold.open = true;
    }
  }
  nav.addEventListener("click", (event) => {
    const link = event.target.closest("a");
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const entry = entries[links.indexOf(link)];
    expose(entry.target);
    if (!wide.matches) panel.open = false;
    entry.target.focus({ preventScroll: true });
  });

  const abort = new AbortController();
  const options = { signal: abort.signal };
  function restoreSection() {
    const entry = entries.find(({ id }) => "#" + id === location.hash);
    if (entry) expose(entry.target);
  }
  restoreSection();
  window.addEventListener("hashchange", restoreSection, options);
  wide.addEventListener("change", () => { panel.open = wide.matches; }, options);

  let frame = 0, active = -1;
  function paint() {
    frame = 0;
    const threshold = document.querySelector(".mast").getBoundingClientRect().bottom + 24;
    let current = 0;
    for (const [i, { target }] of entries.entries()) {
      if (target.getClientRects().length && target.getBoundingClientRect().top <= threshold) current = i;
    }
    if (current === active) return;
    if (active >= 0) links[active].removeAttribute("aria-current");
    links[current].setAttribute("aria-current", "location");
    active = current;
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
  window.addEventListener("scroll", schedule, { ...options, passive: true });
  window.addEventListener("resize", schedule, options);
  article.addEventListener("toggle", schedule, { ...options, capture: true });
  paint();
  dispose = () => { abort.abort(); cancelAnimationFrame(frame); };
}
