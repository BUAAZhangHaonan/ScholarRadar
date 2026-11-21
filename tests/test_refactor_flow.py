import asyncio, json
from datetime import date
from unittest.mock import patch
from test_semantics import DatabaseCase
from scholar_radar import acquisition
from scholar_radar.bibliography import shortlist
from scholar_radar.candidate_pool import remember
from scholar_radar.changes import pending
from scholar_radar.db import database, key
from scholar_radar.evidence import work, resource
from scholar_radar.feedback import feedback
from scholar_radar.period_history import evolution
from scholar_radar.profile import get_profile
from scholar_radar.queue import enqueue
from scholar_radar.recommendations import record, paper_features, signals
from scholar_radar.releases import register
from scholar_radar.settings import now, dump


class RefactorFlow(DatabaseCase):
    def test_all_five_read_uses_backlog_and_full_late_abstract(self):
        day = date(2026, 11, 20)
        with database(write=True) as db:
            rid = enqueue(db, "daily", day)
            run = dict(db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())
            run["detail"] = dump({"cold": False})
            remote = []
            for i in range(5):
                p = {
                    "title": "Previously read " + str(i),
                    "s2_id": "seen" + str(i),
                    "doi": "10.1234/seen" + str(i),
                    "abstract": "old",
                }
                wid = work(db, p["title"], {"s2": p["s2_id"], "doi": p["doi"]}, p)
                p["work_id"] = wid
                remember(db, p)
                db.execute(
                    "INSERT INTO readings VALUES(?,?,?,'done','{}')",
                    (rid, p["s2_id"], dump(p)),
                )
                remote.append(p)
            for i in range(4):
                p = {
                    "title": "Uninformative title " + str(i),
                    "s2_id": "new" + str(i),
                    "doi": "10.1234/new" + str(i),
                    "abstract": "background " * 90
                    + ("DISTINCTIVE LATE RESULT" if i == 2 else "other"),
                }
                p["work_id"] = work(db, p["title"], {"s2": p["s2_id"]}, p)
                remember(db, p)

        async def trace(*args):
            return {"status": "success", "papers": remote}

        async def more(*args):
            raise AssertionError("existing unread supply was ignored")

        async def model(role, model, instr, packet, *args):
            hits = [
                p
                for p in packet["candidates"]
                if "DISTINCTIVE LATE RESULT" in p["abstract"]
            ]
            return {
                "selected": [
                    {
                        "id": p["id"],
                        "reason": "从完整摘要定位对照",
                        "direction_ids": ["pre-generation-risk"],
                    }
                    for p in hits
                ]
            }

        with (
            patch.object(acquisition, "VAR", self.root),
            patch.object(acquisition, "discover_papers", trace),
            patch.object(acquisition, "recent_candidates", more),
            patch("scholar_radar.bibliography.ask", model),
        ):
            asyncio.run(acquisition.collect(run))
            info = asyncio.run(acquisition.screen(run))
            self.assertEqual(info["selected"], 1)
        with database() as db:
            p = json.loads(
                db.execute(
                    "SELECT paper FROM readings WHERE status='queued' AND run_id=?",
                    (rid,),
                ).fetchone()[0]
            )
            self.assertEqual(p["s2_id"], "new2")
            self.assertEqual(p["direction_ids"], ["pre-generation-risk"])

    def test_resource_reachability_alone_does_not_change_research(self):
        with database(write=True) as db:
            wid = work(db, "Study", {"s2": "v"})
            resource(db, wid, "https://github.com/example/fixture", "code")
            res = db.execute("SELECT id FROM resources").fetchone()[0]
            db.execute(
                "INSERT INTO memberships VALUES(?,?,'1','[]',?)",
                ("pre-generation-risk", wid, now()),
            )
            self.assertEqual(register(db, res, []), [])
            self.assertEqual(pending(db), [])
            f = {
                "kind": "code",
                "path": "src/model.py",
                "version": "abc",
                "url": "https://github.com/example/fixture/blob/test/src/model.py",
                "source_url": "https://api.github.com/repos/example/fixture/git/trees/test",
                "raw": '{"path":"src/model.py","sha":"abc"}',
                "locator": "abc",
                "source_version": "test",
            }
            self.assertEqual(len(register(db, res, [f])), 1)
            self.assertEqual(register(db, res, [f]), [])
            self.assertEqual(
                [x["direction_id"] for x in pending(db)], ["pre-generation-risk"]
            )

    def test_weekly_keeps_baseline_counterevidence_and_narrower_judgment(self):
        with database(write=True) as db:
            pid = get_profile(db)["id"]
            for i, day in enumerate(
                (
                    date(2026, 11, 14),
                    date(2026, 11, 16),
                    date(2026, 11, 18),
                    date(2026, 11, 20),
                )
            ):
                rid = enqueue(db, "daily", day)
                sid = key(i)
                body = {
                    "judgment": str(i),
                    "change": ["期初判断", "出现支持", "反例", "适用条件收窄"][i],
                }
                stamp = day.isoformat() + "T01:00:00+00:00"
                db.execute(
                    "INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        "tool-constraint",
                        rid,
                        stamp,
                        stamp,
                        pid,
                        "scope",
                        "1",
                        dump(body),
                        key("input", i),
                    ),
                )
                db.execute(
                    "INSERT INTO assessment_reviews VALUES(?,?,?,?,?,?)",
                    (
                        sid,
                        stamp,
                        ("needs_evidence" if i == 2 else "supported"),
                        "reason",
                        "[]",
                        "fixture",
                    ),
                )
            chain = evolution(
                db, date(2026, 11, 15), date(2026, 11, 21), "Asia/Shanghai"
            )[0]["nodes"]
            self.assertTrue(chain[0]["baseline"])
            self.assertEqual(
                [x["change"] for x in chain],
                ["期初判断", "出现支持", "反例", "适用条件收窄"],
            )

    def test_feedback_only_applies_to_the_paper_version_actually_rated(self):
        with database(write=True) as db:
            profile = get_profile(db)
            paper = {"title": "研究", "abstract": "完整摘要", "arxiv_id": "2401.12345"}
            paper["work_id"] = work(db, "研究", {"arxiv": paper["arxiv_id"]}, paper)
            rec = record(
                db,
                "work",
                paper["work_id"],
                "明确对照",
                paper_features(paper),
                pid=profile["id"],
            )
            feedback(
                db,
                "work",
                paper["work_id"],
                "reading_status",
                "read",
                "",
                "read",
                recommendation_id=rec,
            )
            self.assertEqual(signals(db), [])
            feedback(
                db,
                "work",
                paper["work_id"],
                "reading_value",
                "irrelevant",
                "这篇的对照不对应当前问题",
                "value",
                recommendation_id=rec,
            )
            self.assertEqual(signals(db)[0]["recommended_because"], "明确对照")

        async def allow(role, model, prompt, inputs, *args):
            self.assertIn("新比较", inputs["candidates"][0]["abstract"])
            return {"selected": [{"id": inputs["candidates"][0]["id"]}]}

        with patch("scholar_radar.bibliography.ask", allow):
            self.assertEqual(asyncio.run(shortlist([paper], profile, 1)), [])
            self.assertEqual(
                len(
                    asyncio.run(
                        shortlist([{**paper, "abstract": "新比较"}], profile, 1)
                    )
                ),
                1,
            )
