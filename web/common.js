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
export async function showEvidence(id) {
  const e = await api("/api/evidence/" + encodeURIComponent(id));
  modal(
    e.title || "官方岗位原文",
    '<p class="meta">' +
      esc(
        (e.version || "文档修订") +
          " · " +
          e.document_revision +
          " · 第 " +
          e.line_start +
          "–" +
          e.line_end +
          " 行",
      ) +
      '</p><div class="context">' +
      esc(e.before) +
      '</div><blockquote class="quote">' +
      esc(e.quote) +
      '</blockquote><div class="context">' +
      esc(e.after) +
      '</div><p><a target="_blank" rel="noopener" href="' +
      safeURL(e.url) +
      '">打开原始来源 ↗</a></p>',
  );
}
export const reqid = () =>
  globalThis.crypto?.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2);
