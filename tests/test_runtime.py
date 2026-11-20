import asyncio
from unittest.mock import patch

from test_semantics import DatabaseCase
from scholar_radar import calls
from scholar_radar.archive import ArchiveUnavailable, put_file
from scholar_radar.db import database
from scholar_radar.queue import enqueue, take, finish
from scholar_radar.replay import replay
from scholar_radar.reports import cost_summary


class Runtime(DatabaseCase):
    def setUp(self):
        super().setUp()
        p = patch.object(calls, "VAR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_lost_paid_response_recovers_same_remote_id(self):
        sent = []
        billed = {}

        async def upstream(args):
            rid = args["analysis_id"]
            sent.append(rid)
            original = {
                "currency": "CNY",
                "lower_cny": "0.12",
                "upper_cny": "0.12",
                "total_cny": "0.12",
            }
            if rid not in billed:
                billed[rid] = 1
                raise ConnectionError("response lost after remote completion")
            return {
                "status": "success",
                "original_cost": original,
                "cost": {"reused_result": True, "currency": "CNY", "total_cny": 0},
            }

        async def request():
            return await calls.invoke(
                "analysis",
                "test",
                {"document": "v1"},
                identity="question",
                id_field="analysis_id",
                transport=upstream,
            )

        with self.assertRaises(ConnectionError):
            asyncio.run(request())
        with database() as db:
            self.assertEqual(
                db.execute("SELECT status FROM calls").fetchone()[0], "unknown_outcome"
            )
        asyncio.run(request())
        asyncio.run(request())
        self.assertEqual(len(set(sent)), 1)
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(billed), 1)
        with database() as db:
            amount = cost_summary(db)
            self.assertAlmostEqual(amount["known_lower"], 0.12)
            self.assertAlmostEqual(amount["historical"], 0.12)

    def test_no_replay_for_non_idempotent_unknown_and_missing_usage(self):
        sent = []

        async def lost(args):
            sent.append(1)
            raise TimeoutError()

        async def run():
            return await calls.invoke(
                "model", "analysis", {}, identity="prompt", transport=lost
            )

        with self.assertRaises(TimeoutError):
            asyncio.run(run())
        with self.assertRaises(calls.CallUnavailable):
            asyncio.run(run())
        self.assertEqual(len(sent), 1)
        with database() as db:
            self.assertIsNone(cost_summary(db)["known_upper"])

    def test_business_failure_and_empty_results_differ(self):
        async def interrupted(args):
            return {"status": "interrupted", "papers": []}

        async def empty(args):
            return {
                "status": "success",
                "papers": [],
                "cost": {
                    "currency": "CNY",
                    "basis": "no_paid_calls",
                    "total_cny": 0,
                    "lower_cny": 0,
                    "upper_cny": 0,
                },
            }

        with self.assertRaises(calls.CallUnavailable):
            asyncio.run(
                calls.invoke("trace", "q", {}, identity="a", transport=interrupted)
            )
        result = asyncio.run(
            calls.invoke("trace", "q", {}, identity="b", transport=empty)
        )
        self.assertEqual(result["papers"], [])
        with database() as db:
            self.assertEqual(
                set(r[0] for r in db.execute("SELECT status FROM calls")),
                {"failed", "done"},
            )

    def test_archive_failure_leaves_pending_without_local_nas_substitute(self):
        source = self.root / "raw.txt"
        source.write_text("原始数据")
        with patch(
            "scholar_radar.archive.remote_command",
            side_effect=ArchiveUnavailable("volume offline"),
        ):
            with self.assertRaises(ArchiveUnavailable):
                put_file(source, "documents/revision.txt")
        with database() as db:
            self.assertEqual(
                db.execute("SELECT status FROM archives").fetchone()[0], "pending"
            )
        self.assertTrue(source.exists())
        self.assertFalse((self.root / "documents").exists())

    def test_reclaim_boundary_and_replay_cutoff(self):
        from datetime import date

        with database(write=True) as db:
            rid = enqueue(db, "daily", date(2026, 11, 21))
            first = take(db, "pid-a")
            second = take(db, "pid-b")
            self.assertEqual(first[1]["id"], second[1]["id"])
            finish(db, rid, second[1]["id"], True, {"resumed": True})
            following = take(db, "pid-b")
            self.assertNotEqual(first[1]["id"], following[1]["id"])
            self.assertEqual(replay(db, "2020-01-01T00:00:00Z")["editions"], [])
