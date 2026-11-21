import { $, esc, showEvidence, msg } from "./common.js";
const routes = {
  "/": "daily",
  "/directions": "directions",
  "/library": "library",
  "/actions": "tasks",
  "/tasks": "tasks",
  "/settings": "settings",
};
for (const nav of document.querySelectorAll("nav a"))
  if (nav.pathname === location.pathname)
    nav.setAttribute("aria-current", "page");
$("#evidence-close").onclick = () => $("#evidence-drawer").close();
$("#close").onclick = () => $("#detail").close();
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-evidence]");
  if (b) showEvidence(b.dataset.evidence).catch((x) => msg(x.message));
});
try {
  const page = await import(
    "./" + (routes[location.pathname] || (location.pathname.startsWith("/directions/")?"directions":location.pathname.startsWith("/works/")?"library":location.pathname.startsWith("/tasks/")?"tasks":"daily")) + ".js"
  );
  await page.render();
} catch (err) {
  $("#app").innerHTML = '<p class="error">' + esc(err.message) + "</p>";
}
