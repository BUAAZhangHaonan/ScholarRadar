import { mountReadingOutline } from "./outline.js";
import {
  $,
  api,
  empty,
  esc,
  evid,
  modal,
  msg,
  safeURL,
  send,
} from "./common.js";
import {
  enableActions,
  humanDate,
  objectFeedback,
  pathFor,
  prose,
} from "./reader.js";

const scopeNames = {
  overview: "阅读所得",
  evaluation: "实验与结果",
  method: "方法",
  limits: "适用条件与局限",
};
const namedFields = [
  ["problem", "研究问题"],
  ["finding", "研究发现"],
  ["mechanism", "方法关键点"],
  ["comparison", "最近邻与对照"],
  ["experiment", "关键实验及其条件"],
  ["conditions", "结论适用于什么情形"],
  ["reuse", "可以复用的部分"],
  ["open_question", "下一步值得补清的问题"],
];
function citations(record, label = "这次阅读的原文") {
  return record.evidence_ids?.length
    ? '<details class="source-fold"><summary>' +
        esc(label) +
        '</summary><div class="row">' +
        record.evidence_ids
          .map((id, i) => evid(id, "引文 " + (i + 1)))
          .join(" ") +
        "</div></details>"
    : "";
}
function readingNotes(records) {
  const mapped = records.filter(
    (r) => r.sections && Object.keys(r.sections).length,
  );
  const referenced = new Map();
  const blocks = namedFields
    .map(([key, title]) => {
      const entries = mapped.filter((r) => r.sections[key]);
      const preferred =
        key === "experiment"
          ? entries.find((r) => r.focus === "evaluation")
          : key === "mechanism"
            ? entries.find((r) => r.focus === "method")
            : null;
      const r = preferred || entries[0];
      if (!r) return "";
      const first = !referenced.has(r.id);
      referenced.set(r.id, r);
      return (
        '<section id="record-' +
        esc(r.id) +
        (first ? "" : "-" + key) +
        '"><h2 data-reading-part="' + key + '">' +
        title +
        "</h2>" +
        prose(r.sections[key]) +
        "</section>"
      );
    })
    .join("");
  const legacy = records.filter(
    (r) => !r.sections || !Object.keys(r.sections).length,
  );
  legacy.sort(
    (a, b) => Number(b.focus === "overview") - Number(a.focus === "overview"),
  );
  const sources = [...referenced.values()]
    .map((r) =>
      citations(r, (r.heading || scopeNames[r.focus] || "研究记录") + "的原文"),
    )
    .join("");
  return (
    blocks +
    (sources ? "<div>" + sources + "</div>" : "") +
    (mapped.length > 1
      ? '<section class="rule-section"><h2 data-reading-part="notes">各次章节研究记录</h2>' +
        mapped.map((r) => '<details class="source-fold" id="note-' + esc(r.id) +
          '"><summary>' + esc(r.heading || scopeNames[r.focus] || "研究记录") +
          '</summary>' + prose(r.answer) + citations(r) + '</details>').join("") + '</section>'
      : "") +
    legacy.map((r) => {
      const title = esc(r.heading || scopeNames[r.focus] || "阅读记录");
      const body = prose(r.answer) + citations(r);
      return mapped.length
        ? '<details class="source-fold" id="note-' + esc(r.id) + '"><summary>' +
          title + '</summary>' + body + '</details>'
        : '<section id="record-' + esc(r.id) + '"><h2 data-reading-part="record">' + title + '</h2>' + body + '</section>';
    }).join("")
  );
}
function sourceLinks(work) {
  if (!work.resources.length) return "";
  return (
    '<details class="rule-section source-fold"><summary data-reading-part="resources">论文提及的代码、模型与数据</summary><ul class="list">' +
    work.resources
      .map(
        (r) =>
          '<li><a href="' +
          safeURL(r.url) +
          '" rel="noopener" target="_blank">' +
          esc(r.url.replace(/^https?:\/\//, "")) +
          " ↗</a>" +
          (r.files?.length
            ? '<ul class="list">' + r.files.map((file) => {
                const kind = {code: "代码", weights: "模型权重", data: "数据文件"}[file.kind];
                return '<li>' + esc(kind) + ' · <a target="_blank" rel="noopener" href="' +
                  safeURL(file.url) + '">' + esc(file.path) + '</a></li>';
              }).join("") + '</ul>'
            : "") +
          "</li>",
      )
      .join("") +
    "</ul></details>"
  );
}
async function detail(id) {
  const work = await api("/api/reading/works/" + encodeURIComponent(id));
  const current = new URL(location.href),
    versions = [...new Set(work.records.map((r) => r.revision_id))];
  const hinted = work.records.find(
    (r) => r.id === current.searchParams.get("record"),
  );
  const wanted = current.searchParams.get("revision") || hinted?.revision_id;
  const chosen = versions.includes(wanted) ? wanted : versions[0];
  const records = work.records.filter((r) => r.revision_id === chosen);
  const versionChoice =
    versions.length > 1
      ? '<label>论文版本<select id="paper-version">' +
        versions
          .map((v, i) => {
            const item = work.records.find((r) => r.revision_id === v);
            return (
              '<option value="' +
              esc(v) +
              '"' +
              (chosen === v ? " selected" : "") +
              ">" +
              esc(item.version || "记录 " + (versions.length - i)) +
              "</option>"
            );
          })
          .join("") +
        "</select></label>"
      : "";
  const paperURL = records[0]?.url || work.url;
  document.title = work.title + " · ScholarRadar";
  $("#app").innerHTML =
    '<a class="breadcrumb" href="/library">← 文献</a><header class="page-head"><div><h1>' +
    esc(work.title) +
    "</h1>" +
    '<div class="row sub">' +
    esc([work.date, records[0]?.version].filter(Boolean).join(" · ")) +
    (paperURL
      ? '　<a href="' +
        safeURL(paperURL) +
        '" target="_blank" rel="noopener">论文原文 ↗</a>'
      : "") +
    "</div></div>" +
    versionChoice +
    "</header>" +
    '<div class="flow paper-reading">' +
    (records.length
      ? readingNotes(records)
      : '<section><h2 data-reading-part="abstract">摘要</h2>' +
        (prose(work.abstract) ||
          empty("这篇论文已进入文献库，尚无阅读记录。")) +
        "</section>") +
    (work.directions.length
      ? '<section class="rule-section"><h2 data-reading-part="connections">与当前方向的关系</h2><ul class="list">' +
        work.directions
          .map(
            (d) =>
              '<li><a href="' +
              pathFor("directions", d.id) +
              '">' +
              esc(d.title) +
              "</a>" +
              (d.title !== d.question ? prose(d.question) : "") +
              "</li>",
          )
          .join("") +
        "</ul></section>"
      : "") +
    sourceLinks(work) +
    (records.length && work.abstract
      ? '<details class="rule-section"><summary>论文摘要</summary>' +
        prose(work.abstract) +
        "</details>"
      : "") +
    objectFeedback(
      "work",
      id,
      current.searchParams.get("snapshot"),
      current.searchParams.get("recommendation"),
    ) +
    (records.length
      ? '<details class="rule-section" id="follow-up-reading"><summary data-reading-part="followup">继续补读</summary><form id="section-read" class="form"><label>想核对的内容<select name="focus">' +
        '<option value="evaluation">实验与结果</option><option value="method">方法</option><option value="limits">局限与讨论</option></select></label><label>原文章节<select name="heading"><option value="">按问题匹配章节</option></select></label><label>希望核对的比较、证据或条件（可选）<textarea name="question" maxlength="1500"></textarea></label><button>加入补读</button></form></details>'
      : "") +
    "</div>";
  mountReadingOutline($(".paper-reading"), "paper");
  if (hinted && hinted.revision_id === chosen) {
    const note = document.getElementById("note-" + hinted.id) || document.getElementById("record-" + hinted.id);
    if (note) {
      if (note.tagName === "DETAILS") note.open = true;
      note.scrollIntoView({block: "start"});
    }
  }
  enableActions($("#app"));
  if ($("#paper-version"))
    $("#paper-version").onchange = (e) => {
      current.searchParams.set("revision", e.target.value);
      location.assign(current);
    };
  const followup = $("#follow-up-reading");
  if (followup) {
    let loaded = false,
      loading = false;
    followup.ontoggle = async () => {
      if (!followup.open || loaded || loading) return;
      loading = true;
      try {
        const sections = await api(
          "/api/works/" +
            encodeURIComponent(id) +
            "/sections?revision_id=" +
            encodeURIComponent(chosen),
        );
        const field = $("#section-read").elements.heading;
        const seen = new Set();
        for (const item of sections) {
          if (typeof item.heading !== "string" || seen.has(item.heading))
            continue;
          seen.add(item.heading);
          const option = document.createElement("option");
          option.value = item.heading;
          option.textContent = item.heading;
          field.append(option);
        }
        loaded = true;
      } catch (ex) {
        msg("暂时无法读取章节目录，仍可按问题匹配章节。");
      } finally {
        loading = false;
      }
    };
  }
  if ($("#section-read"))
    $("#section-read").onsubmit = async (e) => {
      e.preventDefault();
      const form = e.currentTarget,
        b = form.querySelector("button");
      b.disabled = true;
      try {
        const resp = await send(
          "/api/works/" +
            encodeURIComponent(id) +
            "/read-section/" +
            form.elements.focus.value,
          {
            revision_id: chosen,
            heading: form.elements.heading.value || null,
            question: form.elements.question.value.trim() || null,
          },
        );
        msg(
          (resp.reused ? "已复用补读任务" : "已提交补读") +
            " · " +
            resp.heading,
        );
      } catch (ex) {
        msg(ex.message);
      } finally {
        b.disabled = false;
      }
    };
}
const kinds = { paper: "论文", code: "代码与数据", job: "岗位", team: "团队" };
async function jobDetail(id) {
  const p = await api("/api/postings/" + encodeURIComponent(id));
  const o = p.observations?.[0],
    ss = {
      advertised: "官方页面已公布",
      closed: "已关闭",
      unavailable: "最近核验时无法访问",
      unknown: "状态待核对",
    };
  modal(
    p.title,
    '<p class="sub">' +
      esc(
        [
          p.published_at ? humanDate(p.published_at) + " 发布" : "",
          o ? ss[o.status] : "",
        ]
          .filter(Boolean)
          .join(" · "),
      ) +
      "</p>" +
      '<p><a href="' +
      safeURL(p.url) +
      '" target="_blank" rel="noopener">打开官方岗位详情 ↗</a></p>' +
      ((o?.details?.evidence_ids || []).length
        ? '<h3>岗位要求原文</h3><div class="row">' +
          o.details.evidence_ids
            .map((e, i) => evid(e, "原文 " + (i + 1)))
            .join(" ") +
          "</div>"
        : ""),
  );
}
async function library() {
  const params = new URLSearchParams(location.search);
  const kind = Object.hasOwn(kinds, params.get("kind"))
    ? params.get("kind")
    : "paper";
  const offset = Math.max(0, Number(params.get("offset")) || 0),
    limit = 25,
    q = params.get("q") || "";
  const result = await api(
    "/api/library?" + new URLSearchParams({ kind, q, offset, limit }),
  );
  document.title = "文献 · ScholarRadar";
  const urlAt = (n) =>
    "/library?" + new URLSearchParams({ kind, q, offset: n });
  $("#app").innerHTML =
    '<header class="page-head catalogue-head"><h1>文献</h1><form id="library-filter" class="catalogue-tools" role="search" aria-label="检索文献与材料">' +
    '<label class="catalogue-kind">材料类型<select name="kind">' +
    Object.entries(kinds)
      .map(
        ([k, v]) =>
          '<option value="' +
          k +
          '"' +
          (k === kind ? " selected" : "") +
          ">" +
          v +
          "</option>",
      )
      .join("") +
    '</select></label><label class="catalogue-query">搜索<input name="q" type="search" value="' +
    esc(q) +
    '" placeholder="题名或原文关键词" maxlength="200"></label><button>查找</button></form></header>' +
    (result.length
      ? '<ul class="list literature-list' + (kind === "paper" ? " paper-catalogue" : "") + '">' +
        result
          .map(
            (item) =>
              "<li><h3>" +
              (kind === "paper"
                ? '<a href="' +
                  pathFor("works", item.id) +
                  '">' +
                  esc(item.title) +
                  "</a>"
                : kind === "job"
                  ? '<button class="link" data-job="' +
                    esc(item.id) +
                    '">' +
                    esc(item.title) +
                    "</button>"
                  : item.url
                    ? '<a href="' +
                      safeURL(item.url) +
                      '" target="_blank" rel="noopener">' +
                      esc(item.title) +
                      " ↗</a>"
                    : esc(item.title)) +
              "</h3>" +
              (kind === "paper"
                ? '<p class="sub">' +
                  esc(
                    [
                      item.published,
                      item.evidence_count ? "可阅读研究记录" : "已收录",
                    ]
                      .filter(Boolean)
                      .join(" · "),
                  ) +
                  "</p>"
                : "") +
              "</li>",
          )
          .join("") +
        "</ul>"
      : empty("没有找到符合条件的材料。") + (q ?
        '<a class="text-action" href="/library?' + esc(new URLSearchParams({ kind }).toString()) +
        '">清除关键词</a>' : "")) +
    '<div class="story-actions">' +
    (offset
      ? '<a class="button quiet" href="' +
        esc(urlAt(Math.max(0, offset - limit))) +
        '">上一页</a>'
      : "") +
    (result.length === limit
      ? '<a class="button quiet" href="' +
        esc(urlAt(offset + limit)) +
        '">下一页</a>'
      : "") +
    "</div>";
  const form = $("#library-filter");
  form.onsubmit = (e) => {
    e.preventDefault();
    location.assign("/library?" + new URLSearchParams(new FormData(form)));
  };
  form.elements.kind.onchange = () => form.requestSubmit();
  document
    .querySelectorAll("[data-job]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          jobDetail(b.dataset.job).catch((e) => msg(e.message))),
    );
}
export async function render() {
  const url = new URL(location.href),
    id = url.pathname.startsWith("/works/")
      ? decodeURIComponent(url.pathname.slice(7))
      : url.searchParams.get("work");
  if (id && url.pathname === "/library") {
    url.pathname = pathFor("works", id);
    url.searchParams.delete("work");
    history.replaceState(history.state, "", url);
  }
  if (id) await detail(id);
  else await library();
}
