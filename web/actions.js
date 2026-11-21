import { $, api, empty, esc, list, modal, msg, reqid, send } from "./common.js";
import { pathFor, prose } from "./reader.js";

const states = {
  proposed: "待决定",
  accepted: "已接受",
  active: "进行中",
  deferred: "已暂缓",
  rejected: "已拒绝",
  completed: "已完成",
};
const transitions = {
  proposed: { accept: "接受", defer: "暂缓", reject: "拒绝" },
  deferred: { accept: "接受", reject: "拒绝" },
  accepted: { start: "开始", defer: "暂缓", reject: "拒绝" },
  active: { complete: "完成", defer: "暂缓" },
};
function entry(a) {
  const fields = [
    ["对照", a.details?.control],
    ["怎么评估", a.details?.metric],
    ["决定是否继续", a.details?.stop],
    ["投入", a.details?.effort],
  ].filter(([, v]) => typeof v === "string" && v);
  return (
    '<article class="card"><p class="eyeline">' +
    esc(states[a.status] || a.status) +
    "</p><h3>" +
    esc(a.title) +
    "</h3>" +
    (fields.length
      ? '<details><summary>研究安排</summary><dl class="kv">' +
        fields
          .map(([k, v]) => "<dt>" + k + "</dt><dd>" + prose(v) + "</dd>")
          .join("") +
        "</dl></details>"
      : "") +
    '<div class="story-actions"><a href="' +
    pathFor("directions", a.dir_id) +
    "?snapshot=" +
    encodeURIComponent(a.snapshot_id) +
    '">回到研究切口</a>' +
    Object.entries(transitions[a.status] || {})
      .map(
        ([k, v]) =>
          '<button class="quiet" data-action="' +
          esc(a.id) +
          '" data-choice="' +
          k +
          '">' +
          v +
          "</button>",
      )
      .join("") +
    "</div></article>"
  );
}
export async function actionArea(root) {
  const [a, b] = await Promise.allSettled([
    api("/api/actions"),
    api("/api/comparisons"),
  ]);
  const actions = a.status === "fulfilled" ? a.value : [],
    blind = b.status === "fulfilled" ? b.value : [];
  const ongoing = actions.filter((x) => x.status !== "proposed"),
    proposed = actions.filter((x) => x.status === "proposed");
  root.innerHTML =
    '<h2 class="section-title">我的行动</h2>' +
    (a.status === "rejected"
      ? '<p class="error">' + esc(a.reason.message) + "</p>"
      : "") +
    '<div class="stack">' +
    (ongoing.map(entry).join("") ||
      (proposed.length
        ? ""
        : empty("接受方向中的行动后，可在这里记录进展。"))) +
    "</div>" +
    (proposed.length
      ? '<details class="source-fold"><summary>可以接受的行动</summary><div class="stack">' +
        proposed.map(entry).join("") +
        "</div></details>"
      : "") +
    (blind.length
      ? '<details class="source-fold"><summary>本期材料比较</summary>' +
        list(
          blind.map(
            (x) =>
              '<a href="' +
              pathFor("works", x.work_id) +
              '">' +
              esc(x.title) +
              '</a><div class="buttons">' +
              [
                ["read", "值得读"],
                ["try", "值得试"],
                ["skip", "暂不选"],
              ]
                .map(
                  ([v, l]) =>
                    '<button class="quiet" data-compare="' +
                    esc(x.work_id) +
                    '" data-value="' +
                    v +
                    '">' +
                    l +
                    "</button>",
                )
                .join("") +
              "</div>",
          ),
        ) +
        "</details>"
      : "");
  root.querySelectorAll("[data-action]").forEach(
    (button) =>
      (button.onclick = () => {
        modal(
          button.textContent + "行动",
          '<form id="decision-form" class="form"><label>取舍原因<select name="reason">' +
            [
              "",
              "与目标匹配",
              "当前没时间",
              "算力条件不足",
              "数据尚未就绪",
              "已做过类似工作",
              "与当前目标不合",
              "其他",
            ]
              .map(
                (v) =>
                  '<option value="' +
                  v +
                  '">' +
                  (v || "选择原因（可选）") +
                  "</option>",
              )
              .join("") +
            '</select></label><label>实际投入、结果或后续问题<textarea name="note"></textarea></label><button>保存决定</button></form>',
        );
        $("#decision-form").onsubmit = async (e) => {
          e.preventDefault();
          const f = new FormData(e.target),
            submit = e.target.querySelector("button");
          submit.disabled = true;
          try {
            await send(
              "/api/actions/" +
                encodeURIComponent(button.dataset.action) +
                "/decision",
              {
                decision: button.dataset.choice,
                reason: f.get("reason") || "",
                actual: { note: f.get("note") || "" },
                request_id: reqid(),
              },
            );
            $("#detail").close();
            msg("已保存");
            await actionArea(root);
          } catch (ex) {
            submit.disabled = false;
            msg(ex.message);
          }
        };
      }),
  );
  root.querySelectorAll("[data-compare]").forEach(
    (button) =>
      (button.onclick = async () => {
        button.disabled = true;
        try {
          await send("/api/feedback", {
            entity_type: "work",
            entity_id: button.dataset.compare,
            dimension: "comparison",
            value: button.dataset.value,
            reason: "",
            request_id: reqid(),
          });
          msg("已记录");
          await actionArea(root);
        } catch (ex) {
          button.disabled = false;
          msg(ex.message);
        }
      }),
  );
}
