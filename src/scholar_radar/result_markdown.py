"""Readable projections of saved research results; never serialize runtime records."""

import json
import re
from urllib.parse import urlsplit


REPORT_NAMES = {"daily": "每日研究整理", "weekly": "每周研究判断", "monthly": "每月研究复盘"}


def _text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ""


def _field(lines, label, value):
    value = _text(value)
    if value:
        lines.extend([f"**{label}**　{value}", ""])


def _link(source):
    title = _text(source.get("title")) or "相关材料"
    version = _text(source.get("version"))
    if version:
        title += " · " + version
    title = title.replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
    url = _text(source.get("url"))
    parsed = urlsplit(url)
    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
        return f"[{title}](<{url}>)"
    return title


def _references(lines, sources):
    links = list(dict.fromkeys(_link(s) for s in sources))
    if links:
        lines.extend(["## 相关论文与材料", "", *["- " + s for s in links], ""])


def _resolve_sources(text, sources):
    """Replace only registered citation IDs, leaving all research prose intact."""
    links = {s.get("source_id") or s.get("id"): _link(s) for s in sources}
    links = {key: value for key, value in links.items() if key}
    if not links:
        return text
    ids = "|".join(re.escape(key) for key in sorted(links, key=len, reverse=True))
    pattern = rf"(?<![\w/])(?:`(?P<code>{ids})`|\[(?P<bracket>{ids})\]|(?P<bare>{ids}))(?![\w])"
    return re.sub(pattern, lambda m: links[next(v for v in m.groups() if v)], text)


def render_report(report):
    """Render one immutable report_versions body, without querying live state."""
    kind = report.get("kind", "daily")
    lines = [f"# {report['date']} · {REPORT_NAMES[kind]}", ""]
    editorial = report.get("editorial") or {}
    review = report.get("review") or {}
    summary = _text(editorial.get("summary") if kind == "daily" else review.get("summary"))
    if summary:
        lines.extend(["## 本期判断", "", summary, ""])
    entries = {entry["snapshot_id"]: entry for entry in editorial.get("items", [])}
    directions = report.get("directions", [])
    for selected in directions:
        card = selected["card"]
        entry = entries.get(selected["id"], {})
        lines.extend(["## " + card["title"], ""])
        _field(lines, "当前判断", card.get("judgment"))
        _field(lines, "这次改变了什么", entry.get("change") or card.get("change"))
        feasibility = card.get("feasibility") or {}
        if isinstance(feasibility, str):
            feasibility = {"asset": feasibility}
        _field(lines, "与我的研究的连接", entry.get("personal_connection") or feasibility.get("asset"))
        _field(lines, "具体问题", card.get("question"))
        _field(lines, "方法与设置", "；".join(filter(None, [_text(card.get("method")), _text(card.get("setting"))])))
        nearest = card.get("nearest")
        if isinstance(nearest, dict):
            _field(lines, "最近邻", nearest.get("title"))
            _field(lines, "已有方法做到什么", nearest.get("similarity"))
            _field(lines, "剩余差别", nearest.get("difference"))
        else:
            _field(lines, "最近邻", nearest)
        _field(lines, "尚缺条件", feasibility.get("needed"))
        _field(lines, "限制", card.get("limitation"))
        for relation in card.get("evidence_relations") or []:
            label = {"supports": "支持证据", "contradicts": "反例证据", "qualifies": "适用边界"}.get(relation.get("relation"), "证据判断")
            _field(lines, label, relation.get("assertion"))
            _field(lines, "成立条件", relation.get("conditions"))
        forecast = card.get("forecast") or {}
        for label, name in (("待验证的预测", "hypothesis"), ("支持条件", "confirm"), ("反驳条件", "refute"), ("观察期限", "horizon")):
            _field(lines, label, forecast.get(name))
        action = card.get("action") or {}
        _field(lines, "下一步", entry.get("next_step") or action.get("title"))
        followup = (report.get("prestudy_followups") or {}).get(selected["id"], {})
        _field(lines, "ARC 留下的问题", followup.get("next_question"))
        history = card.get("history") or []
        if history:
            lines.extend(["### 相关工作的演进", ""])
            for event in history:
                stamp = event.get("date") or ("首次观察 " + str(event.get("first_observed", ""))[:10])
                lines.append(f"- {stamp}：{_text(event.get('event'))}")
            lines.append("")
    if not directions and not summary:
        lines.extend(["本期没有形成通过证据校验的新方向判断。", ""])
    if report.get("research_updates"):
        lines.extend(["## 论文阅读动态", ""])
        for update in report["research_updates"]:
            title = update["title"] + (" · " + update["version"] if update.get("version") else "")
            lines.extend(["### " + title, "", _text(update.get("body")), ""])
    if report.get("evolution"):
        lines.extend(["## 期间判断如何变化", ""])
        for direction in report["evolution"]:
            lines.extend(["### " + direction["title"], ""])
            for node in direction["nodes"]:
                lines.extend(["#### " + node["date"] + (" · 期初判断" if node.get("baseline") else ""), ""])
                _field(lines, "判断", node.get("judgment"))
                _field(lines, "变化", node.get("change"))
                _field(lines, "仍需核查", node.get("open_issue"))
                for action in node.get("actions", []):
                    _field(lines, "行动", action.get("title"))
                    _field(lines, "实际结果", action.get("actual"))
                    _field(lines, "原因", action.get("reason"))
                for feedback in node.get("feedback", []):
                    _field(lines, "用户评价", feedback.get("reason") or feedback.get("value"))
    proposal = review.get("proposal") or {}
    proposed = next((a for a in report.get("proposed_actions", []) if (a.get("action_id") or a.get("id")) == proposal.get("action_id")), None)
    if proposed:
        lines.extend(["## 建议的下一次验证", ""])
        _field(lines, "行动", proposed.get("title"))
        _field(lines, "为什么现在做", proposal.get("why"))
    unresolved = review.get("unresolved") or []
    if isinstance(unresolved, str):
        unresolved = [unresolved]
    pending = [_text(item.get("question") if isinstance(item, dict) else item) for item in unresolved]
    pending.extend("：".join(filter(None, [_text(item.get("question")), _text(item.get("reason"))])) for item in report.get("watch", []))
    pending = list(dict.fromkeys(value for value in pending if value))
    if pending:
        lines.extend(["## 尚待解决", "", *["- " + value for value in pending], ""])
    _references(lines, report.get("evidence", []))
    return _resolve_sources("\n".join(lines).rstrip() + "\n", report.get("evidence", []))


def render_arc(handoff):
    """Render the saved ARC presentation, retaining research draft when unpolished."""
    result = json.loads(handoff["result_json"] or "{}")
    bundle = json.loads(handoff.get("bundle_json") or "{}")
    title = _text((bundle.get("proposal") or {}).get("title")) or _text(handoff.get("direction_title")) or "研究问题"
    stage = {"develop": "展开研究方案", "run": "检查关键前提"}.get(handoff["stage"], "ARC 研究整理")
    lines = [f"# {stage} · {title}", ""]
    _field(lines, "本阶段的问题", handoff.get("focus"))
    decision = {"discuss": "值得继续讨论", "lead": "保留为线索", "drop": "暂时放下"}.get(result.get("research_decision"))
    _field(lines, "研究判断", decision)
    if result.get("evidence_limited"):
        lines.extend(["当前证据有限，以下判断仍有待核实。", ""])
    presentation = result.get("presentation") or {}
    polished = bool(presentation.get("stage_summary") or presentation.get("overview") or any(c.get("text") for c in presentation.get("candidates", [])))
    if polished:
        lines.extend(["## 本阶段结论", ""])
        _field(lines, "核心结论", presentation.get("stage_summary"))
        overview = _text(presentation.get("overview"))
        if overview:
            lines.extend([overview, ""])
        for candidate in presentation.get("candidates", []):
            lines.extend(["## " + (_text(candidate.get("presentation_title")) or "研究方案"), "", _text(candidate.get("text")), ""])
            technical = _text(candidate.get("technical_analysis"))
            if technical:
                lines.extend(["### 技术分析与验证", "", technical, ""])
    elif _text(result.get("draft_text")):
        lines.extend(["## 研究原稿", "", result["draft_text"].strip(), ""])
    else:
        draft = result.get("draft") or {}
        if isinstance(draft, str):
            lines.extend(["## 研究原稿", "", draft.strip(), ""])
        else:
            for label, name in (("研究原稿", "text"), ("概述", "overview"), ("判断依据", "reason"), ("决策理由", "decision_reason"), ("可行性", "feasibility"), ("主要风险", "main_risk"), ("限制", "limits"), ("认识的变化", "changes_from_seed")):
                _field(lines, label, draft.get(name))
    technical = _text(presentation.get("technical_analysis"))
    if technical:
        lines.extend(["## 技术分析", "", technical, ""])
    understanding = result.get("current_understanding")
    if isinstance(understanding, dict):
        lines.extend(["## 当前认识与未决前提", ""])
        for label, name in (("核心认识", "core_insight"), ("具体例子", "illustrative_example"), ("已撤回的前提", "invalidated_premises"), ("关键未知", "decisive_unknown"), ("现有研究为何不足", "why_existing_insufficient")):
            _field(lines, label, understanding.get(name))
    else:
        _field(lines, "当前认识", understanding)
    _field(lines, "下一步需要回答", result.get("next_question"))
    sources = result.get("source_directory", [])
    _references(lines, sources)
    return _resolve_sources("\n".join(lines).rstrip() + "\n", sources)
