import json
import unittest

from scholar_radar.result_markdown import render_arc, render_report


class ReadableResults(unittest.TestCase):
    def test_report_keeps_scientific_content_without_runtime_fields(self):
        report = {
            "kind": "daily", "date": "2026-11-21",
            "editorial": {"summary": "位置基线改变了比较起点。", "items": [{
                "snapshot_id": "snapshot", "change": "应先控制位置混淆。",
                "personal_connection": "连接现有的视觉冲突问题。", "next_step": "固定问题，移除不同物体。",
            }]},
            "directions": [{"id": "snapshot", "card": {
                "title": "视觉冲突的可区分对照", "judgment": "区分目标特异性。", "change": "旧版变化",
                "question": "目标移除是否导致答案翻转？", "method": "匹配对照", "setting": "固定问题",
                "evidence_relations": None,
                "feasibility": {"asset": "旧版切口", "needed": "一组匹配样本"},
                "nearest": {"title": "位置基线研究", "similarity": "预测位置", "difference": "改变视觉目标"},
                "forecast": {"hypothesis": "可预测目标特异的翻转", "confirm": ["高于位置基线"], "refute": ["无关物体同样有效"]},
                "action": {"title": "旧版动作"}, "history": [{"date": "2026-11-20", "event": "发现位置基线"}],
            }}],
            "research_updates": [{"title": "SAVOR", "version": "v1", "body": "隐藏态包含答案变化线索。"}],
            "evidence": [{"id": "citation-id", "title": "位置基线研究", "url": "https://arxiv.org/abs/2401.00001v2", "version": "v2"}],
            "cost": {"known_lower": "PRIVATE-COST"},
            "coverage": {"sources": [{"reason": "PRIVATE-CONSOLE"}]},
            "issues": [{"outcome": "PRIVATE-LOG"}], "profile_version": "PRIVATE-PROFILE",
        }
        text = render_report(report)
        for expected in ("位置基线改变了比较起点", "应先控制位置混淆", "连接现有的视觉冲突问题", "固定问题，移除不同物体", "无关物体同样有效", "隐藏态包含答案变化线索", "https://arxiv.org/abs/2401.00001v2"):
            self.assertIn(expected, text)
        for absent in ("PRIVATE-", "旧版切口", "旧版动作", "旧版变化"):
            self.assertNotIn(absent, text)

    def test_weekly_preserves_changed_judgment_and_actual_outcomes(self):
        text = render_report({
            "kind": "weekly", "date": "2026-11-22", "directions": [],
            "review": {"summary": "比较范围收窄。", "proposal": {"action_id": "action", "why": "区分两种解释"}, "unresolved": ["训练数据是否可用？"]},
            "proposed_actions": [{"id": "action", "title": "完成样本配对"}],
            "evolution": [{"title": "视觉目标", "nodes": [
                {"date": "2026-11-14", "baseline": True, "judgment": "原本认为通用", "actions": [], "feedback": []},
                {"date": "2026-11-20", "judgment": "只适用于目标移除", "open_issue": "仍缺反例", "actions": [{"title": "样本检查", "actual": "发现干扰因素", "reason": "目标大小不匹配"}], "feedback": [{"reason": "有助于缩小课题"}]},
            ]}],
        })
        for expected in ("比较范围收窄", "期初判断", "原本认为通用", "只适用于目标移除", "发现干扰因素", "有助于缩小课题", "完成样本配对", "训练数据是否可用"):
            self.assertIn(expected, text)

    def test_arc_preserves_presentation_and_structured_understanding(self):
        result = {
            "research_decision": "discuss", "evidence_limited": True,
            "presentation": {
                "stage_summary": "先固定相同材料。", "overview": "来源 [source-one] 提供了对照。",
                "candidates": [{"text": "比较信息到达的时机。", "technical_analysis": "单独检查任务难度。"}],
                "technical_analysis": "使用配对样本。",
            },
            "current_understanding": {"core_insight": "两种解释可区分", "invalidated_premises": ["位置可以忽略"], "decisive_unknown": "区别是否保留", "why_existing_insufficient": "缺少时机对照"},
            "next_question": "目标移除是否有特异性？",
            "source_directory": [{"source_id": "source-one", "title": "时机研究", "url": "https://example.org/paper", "version": "v1", "content": "PRIVATE-FULLTEXT"}],
            "cost": "PRIVATE-COST", "polish_failure": "PRIVATE-LOG",
        }
        text = render_arc({"stage": "run", "focus": "排除难度解释", "bundle_json": json.dumps({"proposal": {"title": "视觉目标对照"}, "profile": {"secret": "PRIVATE-PROFILE"}, "sources": [{"content": "PRIVATE-FULLTEXT"}]}), "result_json": json.dumps(result)})
        for expected in ("检查关键前提 · 视觉目标对照", "先固定相同材料", "单独检查任务难度", "使用配对样本", "两种解释可区分", "位置可以忽略", "缺少时机对照", "[时机研究 · v1](<https://example.org/paper>)"):
            self.assertIn(expected, text)
        self.assertNotIn("source-one", text)
        self.assertNotIn("PRIVATE-", text)

    def test_arc_writer_failure_keeps_draft_and_legacy_source_id(self):
        text = render_arc({"stage": "develop", "focus": "区分解释", "result_json": json.dumps({
            "presentation_status": "draft", "draft_text": "研究原稿仍可读，见 `legacy-id`。",
            "current_understanding": "只能支持较窄条件", "next_question": "补做匹配对照",
            "source_directory": [{"id": "legacy-id", "title": "对照论文", "url": "https://example.org/control"}],
            "polish_failure": {"reason": "PRIVATE-LOG"},
        })})
        self.assertIn("研究原稿仍可读", text)
        self.assertIn("[对照论文](<https://example.org/control>)", text)
        self.assertIn("只能支持较窄条件", text)
        self.assertNotIn("legacy-id", text)
        self.assertNotIn("PRIVATE-LOG", text)


if __name__ == "__main__":
    unittest.main()
