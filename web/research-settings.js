import { $, api, esc, send, msg } from "./common.js";
export async function controls(root) {
  const [scope, factors] = await Promise.all([
    api("/api/scopes"),
    api("/api/factors"),
  ]);
  const region = document.createElement("section");
  region.className = "panel";
  const labels = {
    proposed: "待审阅",
    reviewed: "已审阅",
    shadow: "后台比较",
    active: "已启用",
    retired: "已退役",
  };
  region.innerHTML =
    '<details><summary>来源范围与候选因子</summary><h3>采集主题</h3><form id="scope-form" class="form"><label>每行一个主题<textarea name="topics">' +
    esc(scope.topics.join("\n")) +
    '</textarea></label><label>固定观察查询<textarea name="query">' +
    esc(scope.arxiv_query) +
    "</textarea></label><button>保存为新的来源版本</button></form><h3>候选因子</h3>" +
    factors.proposals
      .map((p) => {
        const f = JSON.parse(p.definition),
          next = { proposed: "reviewed", reviewed: "shadow", shadow: "active" }[
            p.lifecycle
          ];
        return (
          "<p>" +
          esc(f.target) +
          "<br><small>" +
          esc(labels[p.lifecycle] || p.lifecycle) +
          " · " +
          esc(f.method) +
          "</small></p>" +
          (next
            ? '<button class="quiet" data-p="' +
              esc(p.id) +
              '" data-s="' +
              next +
              '">' +
              esc(labels[next]) +
              "</button>"
            : "")
        );
      })
      .join("") +
    "</details>";
  root.appendChild(region);
  $("#scope-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await send(
        "/api/scopes",
        {
          topics: String(f.get("topics"))
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
          arxiv_query: f.get("query"),
        },
        "PUT",
      );
      msg("新的采集范围将在新任务使用");
    } catch (x) {
      msg(x.message);
    }
  };
  region.querySelectorAll("[data-p]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await send(
            "/api/factors/proposals/" + b.dataset.p + "/" + b.dataset.s,
            {},
          );
          region.remove();
          await controls(root);
          msg("已保存因子状态");
        } catch (x) {
          msg(x.message);
        }
      }),
  );
}
