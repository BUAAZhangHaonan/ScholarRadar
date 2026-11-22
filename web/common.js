export const $ = (selector, root = document) => root.querySelector(selector);
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const txt = (value) =>
  typeof value === "object" && value !== null
    ? Object.values(value)
        .filter((v) => typeof v === "string")
        .join(" · ")
    : String(value ?? "");
export const safeURL = (value) => {
  try {
    const u = new URL(value);
    return ["http:", "https:"].includes(u.protocol) ? esc(u.href) : "#";
  } catch {
    return "#";
  }
};
export async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 401) {
    location.assign("/login");
    throw Error("请先登录");
  }
  const data = await response.json();
  if (!response.ok)
    throw Error(typeof data.detail === "string" ? data.detail : "请求参数无效");
  return data;
}
export const send = (path, data, method = "POST") =>
  api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
export const heading = (title, note = "") =>
  '<div class="lead"><div><h1>' +
  esc(title) +
  "</h1>" +
  (note ? '<div class="sub">' + esc(note) + "</div>" : "") +
  "</div></div>";
export const empty = (t) => '<p class="empty">' + esc(t) + "</p>";
export const evid = (id, n) =>
  '<button class="link" data-evidence="' +
  esc(id) +
  '">' +
  esc(n || "查看引文") +
  "</button>";
export const list = (items) =>
  '<ul class="list">' +
  items.map((s) => "<li>" + s + "</li>").join("") +
  "</ul>";
export const msg = (t) => {
  const p = $("#toast");
  p.textContent = t;
  p.hidden = false;
  setTimeout(() => (p.hidden = true), 3500);
};
export function modal(title, html) {
  $("#detail-title").textContent = title;
  $("#detail-body").innerHTML = html;
  const d = $("#detail");
  if (!d.open) d.showModal();
}
let citationRequest = 0;
export async function showEvidence(id) {
  const ticket = ++citationRequest;
  const opener = document.activeElement;
  const scroll = [window.scrollX, window.scrollY];
  const evidence = await api("/api/evidence/" + encodeURIComponent(id));
  if (ticket !== citationRequest) return;
  const drawer = $("#evidence-drawer");
  $("#evidence-title").textContent = evidence.title || "原始材料";
  const contextIds = [];
  function context(text, side) {
    if (!text?.trim()) return "";
    const id = 'quote-' + side;
    contextIds.push(id);
    return '<div id="' + id + '" class="evidence-context context" hidden>' + esc(text) + '</div>';
  }
  const before = context(evidence.before, "before"), after = context(evidence.after, "after");
  const line = Number.isInteger(evidence.line_start)
    ? "第 " + evidence.line_start + (evidence.line_end > evidence.line_start ? "–" + evidence.line_end : "") + " 行"
    : "";
  const where = [evidence.version, line].filter(Boolean).join(" · ");
  $("#evidence-body").innerHTML =
    (where ? '<p class="sub">' + esc(where) + '</p>' : "") + before +
    '<blockquote class="quote">' + esc(evidence.quote) + '</blockquote>' + after +
    '<div class="drawer-tools">' +
    (contextIds.length ? '<button type="button" class="link" id="toggle-context" aria-expanded="false" aria-controls="' +
      contextIds.join(" ") + '">展开上下文</button>' : "") +
    '<a target="_blank" rel="noopener" href="' + safeURL(evidence.url) + '">打开原始来源 ↗</a></div>';
  const toggle = $("#toggle-context");
  if (toggle) toggle.onclick = () => {
    const expanded = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.textContent = expanded ? "收起上下文" : "展开上下文";
    for (const id of contextIds) document.getElementById(id).hidden = !expanded;
  };
  drawer.addEventListener(
    "close",
    () => {
      if (opener?.isConnected) opener.focus({ preventScroll: true });
      window.scrollTo(...scroll);
    },
    { once: true },
  );
  if (!drawer.open) drawer.showModal();
  drawer.scrollTop = 0;
}
export const reqid = () =>
  globalThis.crypto?.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2);
