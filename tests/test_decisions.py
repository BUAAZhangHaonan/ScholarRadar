import asyncio
import json
from datetime import date
from unittest.mock import patch

from test_semantics import DatabaseCase
from scholar_radar import reports
from scholar_radar.db import database
from scholar_radar.evidence import revision, span, work
from scholar_radar.factors import propose, transition
from scholar_radar.operations_api import RunRequest, trigger
from scholar_radar.queue import enqueue
from scholar_radar.shadow import active_signals, measure


class Decisions(DatabaseCase):
    def test_active_and_shadow_signals_have_distinct_effects(self):
        with database(write=True) as db:
            wid = work(db, "研究样例", {"s2": "factor-fixture"})
            rv = revision(
                db, wid, "https://example.org/paper", "paper", "v1", "一段材料"
            )
            span(db, rv, 0, 4, "一段材料")
            pid = propose(
                db,
                {
                    "target": "阅读价值",
                    "input": "定位",
                    "method": "has_located_evidence",
                    "window_days": 28,
                    "missing": "未知",
                    "overlap": "证据进展",
                    "comparison": "基准",
                },
            )
            transition(db, pid, "reviewed")
            transition(db, pid, "shadow")
            self.assertEqual(active_signals(db, wid, "2099-01-01"), {})
            self.assertEqual(measure(db, "has_located_evidence", wid, "2000-01-01"), 0)
            transition(db, pid, "active")
            self.assertEqual(active_signals(db, wid, "2099-01-01"), {"阅读价值": 1})

    def test_monthly_review_uses_the_previous_calendar_month(self):
        with database(write=True) as db:
            rid = enqueue(db, "monthly", date(2026, 12, 1))
            run = dict(db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())
        with patch.object(reports, "ROOT", self.root):
            asyncio.run(reports.publish(run))
        with database() as db:
            body = json.loads(
                db.execute(
                    "SELECT body FROM reports WHERE run_id=?", (rid,)
                ).fetchone()[0]
            )
            self.assertEqual(
                (body["coverage"]["window_start"], body["coverage"]["window_end"]),
                ("2026-11-01", "2026-11-30"),
            )
            self.assertEqual(body["directions"], [])

    def test_duplicate_manual_request_returns_reuse(self):
        request = RunRequest(kind="daily", day=date(2026, 1, 1))
        first = trigger(request)
        second = trigger(request)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["run_id"], second["run_id"])
