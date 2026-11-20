import { $, api, esc, txt, evid, list, empty, heading } from "./common.js";
const periods = { daily: "日报", weekly: "周报", monthly: "月报" };
function card(s) {
  const d = s.card,
    f = d.forecast;
  const history = d.history
    .map(
      (h) =>
        "<li><time>" +
        esc(h.date || "观察于 " + h.first_observed.slice(0, 10)) +
        "</time>" +
        esc(h.event) +
        " " +
        evid(h.evidence_ids[0], "原文") +
        "</li>",
    )
    .join("");
  return (
    '<article class="card feature"><h2>' +
    esc(d.title) +
    "</h2><p>" +
    esc(d.judgment) +
    '</p><div class="label">研究脉络</div><ol class="timeline">' +
    history +
    '</ol><div class="label">本次变化</div><p>' +
    esc(d.change) +
    '</p><div class="label">待验证的预测 · ' +
    esc(f.horizon) +
    "</div><p>" +
    esc(f.hypothesis) +
    "</p><details><summary>什么证据会改变这个判断</summary><p>支持条件　" +
    esc(txt(f.confirm)) +
    "</p><p>反例条件　" +
    esc(txt(f.refute)) +
    '</p></details><div class="label">下一步</div><p>' +
    esc(d.action.title) +
    '</p><a href="/directions?id=' +
    encodeURIComponent(s.direction_id) +
    '">查看方向历史 ↗</a></article>'
  );
}
export async function render(kind = "daily", day = "") {
  const [data, status] = await Promise.all([
    api(
      "/api/daily?kind=" +
        kind +
        (day ? "&date=" + encodeURIComponent(day) : ""),
    ),
    api("/api/status"),
  ]);
  const sources = data.coverage?.sources || [];
  const sourceStates = [...new Map(sources.map((s) => [s.source, s])).values()];
  const review = data.review;
  $("#app").innerHTML =
    heading(
      kind === "daily"
        ? "今日变化"
        : kind === "weekly"
          ? "每周研究判断"
          : "每月复盘",
      data.date ? data.date + " · 北京时间" : "按发布日期查看",
    ) +
    '<div class="controls"><div class="chips">' +
    Object.entries(periods)
      .map(
        ([k, v]) =>
          '<button class="chip ' +
          (kind === k ? "active" : "") +
          '" data-period="' +
          k +
          '">' +
          v +
          "</button>",
      )
      .join("") +
    '</div><label>报告日期<input id="report-date" type="date" value="' +
    esc(day || data.date || "") +
    '"></label></div><div class="layout"><div class="stack">' +
    (review
      ? '<section class="panel"><h2>本期判断</h2><p>' +
        esc(review.summary) +
        '</p><div class="row">' +
        (review.readings || [])
          .map((id, i) => evid(id, "精读 " + (i + 1)))
          .join(" ") +
        "</div></section>"
      : "") +
    ((data.directions || []).map(card).join("") ||
      '<section class="panel">' +
        empty(
          data.pending
            ? "所选日期暂无已发布报告。"
            : "当期没有通过证据校验的新变化。已有方向和历史证据可以在方向库查看。",
        ) +
        "</section>") +
    '</div><aside class="stack"><section class="panel"><h3>来源覆盖</h3>' +
    (sourceStates.length
      ? list(
          sourceStates.map(
            (s) =>
              "<strong>" +
              esc(s.source) +
              "</strong><br><small>" +
              esc(
                s.status === "ok" || s.status === "success"
                  ? "已取得记录"
                  : s.reason || s.status,
              ) +
              "</small>",
          ),
        )
      : empty("报告完成后显示本期采集范围。")) +
    '</section><section class="panel"><h3>证据库</h3><p><span class="meta">' +
    esc(status.works) +
    '</span> 项作品　<span class="meta">' +
    esc(status.evidence) +
    '</span> 处原文</p><a href="/library">检索材料 ↗</a></section>' +
    (data.cost
      ? '<section class="panel"><h3>本期调用</h3><p class="meta">已知下界 ¥' +
        esc(data.cost.known_lower) +
        "<br>待核算 " +
        esc(data.cost.unknown) +
        ' 项</p><a href="/settings">查看运行记录 ↗</a></section>'
      : "") +
    "</aside></div>";
  document
    .querySelectorAll("[data-period]")
    .forEach((b) => (b.onclick = () => render(b.dataset.period)));
  $("#report-date").onchange = (e) => render(kind, e.target.value);
}
