import { $, api, esc, heading, msg, send } from "./common.js";

function lines(value) {
  return String(value ?? "")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}
export async function render() {
  const p = await api("/api/profile");
  document.title = "个人设置 · ScholarRadar";
  $("#app").innerHTML =
    heading("个人设置") +
    '<form id="preferences" class="form profile-form">' +
    '<section class="panel"><h2>当前研究</h2><div class="form"><label>研究目标（每行一项）<textarea name="goals">' +
    esc(p.goals.join("\n")) +
    "</textarea></label>" +
    '<label>正在推进的项目（每行一项）<textarea name="projects">' +
    esc((p.current_actions || []).join("\n")) +
    "</textarea></label>" +
    '<label>个人研究资产<textarea name="assets" rows="5">' +
    esc(p.assets.map((a) => a.name || "").join("\n")) +
    "</textarea></label>" +
    '</div></section><section class="panel"><h2>节奏与投入</h2><div class="two">' +
    '<label>时区<input name="timezone" required value="' +
    esc(p.timezone) +
    '"></label><label>日报时间<input name="daily_time" type="time" required value="' +
    esc(p.daily_time) +
    '"></label>' +
    '<label>日报重点条数<input name="daily_limit" type="number" required min="0" max="5" value="' +
    p.daily_limit +
    '"></label>' +
    '<label>同时进行的验证<input name="active_limit" type="number" required min="1" max="10" value="' +
    p.active_limit +
    '"></label>' +
    '</div></section><div class="buttons"><button>保存个人设置</button><a href="/maintenance">运行维护</a></div></form>' +
    '<details class="rule-section" id="profile-all"><summary>完整画像与模型设置</summary><form class="form" id="edit-json"><label>完整画像 JSON<textarea name="content" rows="15">' +
    esc(JSON.stringify(p, null, 2)) +
    "</textarea></label><button>保存完整画像</button></form></details>";
  $("#preferences").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target),
      bank = new Map(p.assets.map((a) => [a.name, a]));
    const newProfile = {
      ...p,
      goals: lines(f.get("goals")),
      current_actions: lines(f.get("projects")),
      assets:
        String(f.get("assets")) === p.assets.map((a) => a.name || "").join("\n")
          ? p.assets
          : lines(f.get("assets")).map(
              (name) => bank.get(name) || { name, source: "用户填写" },
            ),
      timezone: f.get("timezone"),
      daily_time: f.get("daily_time"),
      daily_limit: Number(f.get("daily_limit")),
      active_limit: Number(f.get("active_limit")),
    };
    try {
      await send("/api/profile", newProfile, "PUT");
      msg("个人设置已保存");
      await render();
    } catch (ex) {
      msg(ex.message);
    }
  };
  $("#edit-json").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const data = JSON.parse(new FormData(e.target).get("content"));
      await send("/api/profile", data, "PUT");
      msg("完整画像已保存");
      await render();
    } catch (ex) {
      msg(ex.message);
    }
  };
}
