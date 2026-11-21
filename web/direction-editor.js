import { $, api, esc, send, msg } from "./common.js";
export async function editor(d, open, container) {
  const panel = document.createElement("details");
  panel.innerHTML =
    '<summary>更多 · 管理方向</summary><form class="form"><label>操作<select name="operation"><option value="rename">更名</option><option value="merge">提议合并</option><option value="split">提议拆分</option></select></label><div data-fields></div><button>保存</button></form><div data-pending></div>';
  container.appendChild(panel);
  const form = $("form", panel),
    fields = $("[data-fields]", panel);
  async function change() {
    const op = form.elements.operation.value;
    if (op === "merge") {
      const dirs = await api("/api/directions");
      fields.innerHTML =
        '<label>合并到<select name="target">' +
        dirs
          .filter((x) => x.id !== d.id && x.status !== "merged")
          .map(
            (x) =>
              '<option value="' + esc(x.id) + '">' + esc(x.title) + "</option>",
          )
          .join("") +
        "</select></label>";
    } else {
      fields.innerHTML =
        '<label>方向名称<input name="title" required value="' +
        esc(op === "rename" ? d.title : "") +
        '"></label>' +
        (op === "split"
          ? [
              ["question", "研究问题"],
              ["method", "方法抓手"],
              ["setting", "评估场景"],
            ]
              .map(
                ([k, v]) =>
                  "<label>" + v + '<input required name="' + k + '"></label>',
              )
              .join("")
          : "");
    }
  }
  form.elements.operation.onchange = change;
  await change();
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await send(
        "/api/directions/" + d.id + "/changes",
        Object.fromEntries(new FormData(form)),
      );
      msg("已记录方向调整");
      await open(d.id);
    } catch (x) {
      msg(x.message);
    }
  };
  const pending = $("[data-pending]", panel);
  pending.innerHTML = d.relations
    .filter((x) => x.status === "proposed")
    .map(
      (x) =>
        '<button class="quiet" data-rel="' +
        esc(x.id) +
        '">确认' +
        (x.relation === "split" ? "拆分" : "合并") +
        "</button>",
    )
    .join(" ");
  pending.querySelectorAll("[data-rel]").forEach(
    (b) =>
      (b.onclick = async () => {
        await send("/api/direction-changes/" + b.dataset.rel + "/confirm", {});
        msg("调整已生效");
        await open(d.id);
      }),
  );
}
