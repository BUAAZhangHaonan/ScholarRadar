import asyncio
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scholar_radar import assessment, changes, db as store
from scholar_radar.db import database, migrate
from scholar_radar.evidence import claim, revision, span, work
from scholar_radar.profile import save
from scholar_radar.queue import enqueue
from scholar_radar.record_store import save_record, work_records, research_updates
from scholar_radar.registry import initialize
from scholar_radar.research_materials import select_papers
from scholar_radar.settings import ROOT, dump


def answer(role, model, instruction, inputs, run_id, **kwargs):
    papers = inputs["papers"]
    ids = [p["work_id"] for p in papers]
    refs = [next(iter(p["quotes"])) for p in papers]
    d = inputs["direction"]
    return {
        "cards": [
            {
                "direction_id": d["id"],
                "title": d["title"],
                "question": d["question"],
                "method": d["method"],
                "setting": d["setting"],
                "judgment": "两个条件的相同测量可以比较。",
                "change": "增加相互补充的观测。",
                "limitation": "尚未知跨域效果。",
                "nearest": {
                    "work_id": ids[0],
                    "title": papers[0]["title"],
                    "similarity": "同一测量",
                    "difference": "改变实验条件",
                },
                "history": [
                    {"work_id": wid, "event": "固定条件的实验", "evidence_ids": [ref]}
                    for wid, ref in zip(ids, refs)
                ],
                "work_ids": ids,
                "evidence_ids": refs,
                "resources": "需核实原始发布",
                "forecast": {
                    "hypothesis": "相同设置下比较两种条件。",
                    "confirm": "方向一致",
                    "refute": "效果相反",
                    "horizon": "首轮",
                    "evidence_ids": refs,
                },
                "feasibility": {"asset": "现有材料", "needed": "统一对照"},
                "job_match": None,
                "action": {
                    "kind": "read",
                    "title": "核对同一设置",
                    "control": "固定评估",
                    "metric": "相同统计量",
                    "stop": "协议不一致",
                    "effort": "阅读",
                },
            }
        ]
    }


class Records(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "_scratch" / "evidence2" / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temp.cleanup)
        patcher = patch.object(store, "DB", Path(temp.name) / "db.sqlite")
        patcher.start()
        self.addCleanup(patcher.stop)
        migrate()
        with database(write=True) as db:
            initialize(db)
            save(
                db,
                {
                    "goals": ["识别视觉错误"],
                    "assets": [],
                    "target_companies": [],
                    "compute": {},
                },
            )
            self.first = enqueue(db, "daily", date(2026, 1, 2))
            self.second = enqueue(db, "daily", date(2026, 1, 3))
            self.run = dict(
                db.execute("SELECT * FROM runs WHERE id=?", (self.second,)).fetchone()
            )
        self.did = "pre-generation-risk"

    def record(
        self,
        db,
        title,
        code,
        version,
        body,
        quote,
        when,
        run,
        *,
        focus="overview",
        topic="",
        targets=(),
        answer_text=None,
    ):
        wid = work(db, title, {"s2": code}, {"published_date": when[:10]})
        rv = revision(
            db,
            wid,
            "https://example.com/" + code,
            "paper",
            code + version,
            body,
            version=version,
        )
        pos = body.index(quote)
        eid = span(db, rv, pos, pos + len(quote), quote)
        q = "检查 " + focus
        statement = answer_text or "关键实验：" + quote
        cid = claim(
            db,
            "system_inference",
            statement,
            [eid],
            [eid],
            {
                "revision": rv,
                "question": q,
                "coverage": {"start": pos, "end": pos + len(quote)},
            },
        )
        save_record(
            db,
            wid=wid,
            rid=rv,
            cid=cid,
            call_id=None,
            analysis_id="fixture-" + cid,
            run_id=run,
            question=q,
            focus=focus,
            heading=None,
            start=pos,
            end=pos + len(quote),
            topic=topic,
            direction_ids=targets,
        )
        db.execute("UPDATE reading_records SET recorded_at=? WHERE id=?", (when, cid))
        return wid, rv, cid, eid

    def test_unpublished_yesterday_can_complete_todays_snapshot(self):
        with database(write=True) as db:
            a = self.record(
                db,
                "Retinal calibration A",
                "a",
                "v1",
                "Calibration baseline.",
                "baseline",
                "2026-01-02T05:00:00+00:00",
                self.first,
            )
            b = self.record(
                db,
                "Retinal calibration B",
                "b",
                "v1",
                "Calibration comparison.",
                "comparison",
                "2026-01-03T05:00:00+00:00",
                self.second,
                targets=[self.did],
            )
            self.assertEqual(
                db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 0
            )
            db.execute(
                "INSERT INTO direction_changes VALUES(?,?,?,?,?,?,NULL)",
                ("event", "reading", b[0], b[2], self.did, "2026-01-03T06:00:00+00:00"),
            )
        with patch.object(
            assessment, "ask", new=AsyncMock(side_effect=answer)
        ) as model:
            outcome = asyncio.run(assessment.assess(self.run))
            self.assertEqual(model.await_count, 1)
            self.assertEqual(asyncio.run(assessment.assess(self.run))["snapshots"], [])
        with database() as db:
            sid = outcome["snapshots"][0]
            refs = {
                r[0]
                for r in db.execute(
                    "SELECT evidence_id FROM snapshot_evidence WHERE snapshot_id=?",
                    (sid,),
                )
            }
            self.assertEqual(refs, {a[3], b[3]})
            self.assertEqual(
                {
                    r[0]
                    for r in db.execute(
                        "SELECT record_id FROM snapshot_reading_records WHERE snapshot_id=?",
                        (sid,),
                    )
                },
                {a[2], b[2]},
            )
            self.assertIsInstance(
                json.loads(
                    db.execute(
                        "SELECT body FROM snapshots WHERE id=?", (sid,)
                    ).fetchone()[0]
                )["nearest"],
                dict,
            )

    def test_v2_late_section_and_its_analysis_replace_v1_for_current_reasoning(self):
        with database(write=True) as db:
            a = self.record(
                db,
                "Retinal calibration",
                "a",
                "v1",
                "old result",
                "old",
                "2026-01-02T01:00:00+00:00",
                self.first,
            )
            long = (
                "Old introduction. " * 1000
                + "New late experiment establishes the comparison."
            )
            b = self.record(
                db,
                "Retinal calibration",
                "a",
                "v2",
                long,
                "Old introduction.",
                "2026-01-03T01:00:00+00:00",
                self.second,
            )
            late = self.record(
                db,
                "Retinal calibration",
                "a",
                "v2",
                long,
                "New late experiment",
                "2026-01-03T02:00:00+00:00",
                self.second,
                focus="evaluation",
            )
            claim(
                db,
                "system_inference",
                "A direction-level inference should never be a paper analysis",
                [a[3]],
                [a[3]],
                {"scope": "direction"},
            )
            p = select_papers(db, self.run, extra_works=[a[0]])[a[0]]
            self.assertEqual(p["revision_id"], b[1])
            self.assertEqual(set(p["quotes"]), {b[3], late[3]})
            self.assertTrue(
                any(r["coverage"]["start"] > 11500 for r in p["reading_records"])
            )
            self.assertNotIn("direction-level", dump(p))
            self.assertEqual(len(work_records(db, a[0])), 3)
            self.assertEqual(len(research_updates(db, self.second)), 1)

    def test_resource_only_change_generates_new_snapshot_for_affected_direction(self):
        with database(write=True) as db:
            w = self.record(
                db,
                "Calibrating vision",
                "x",
                "v1",
                "A reading.",
                "reading",
                "2026-01-03T01:00:00+00:00",
                self.second,
                targets=[self.did],
            )
            db.execute(
                "INSERT INTO direction_changes VALUES(?,?,?,?,?,?,NULL)",
                ("r1", "reading", w[0], w[2], self.did, "2026-01-03T02:00:00+00:00"),
            )
        with patch.object(
            assessment, "ask", new=AsyncMock(side_effect=answer)
        ) as model:
            first = asyncio.run(assessment.assess(self.run))
            with database(write=True) as db:
                db.execute(
                    "INSERT INTO direction_changes VALUES(?,?,?,?,?,?,NULL)",
                    (
                        "r2",
                        "resource",
                        "source",
                        "released-code",
                        self.did,
                        "2026-01-03T03:00:00+00:00",
                    ),
                )
            second = asyncio.run(assessment.assess(self.run))
            self.assertEqual(model.await_count, 2)
            self.assertTrue(
                all(
                    x.args[3]["direction"]["id"] == self.did
                    for x in model.await_args_list
                )
            )
        self.assertNotEqual(first["snapshots"], second["snapshots"])
        with database() as db:
            val = json.loads(
                db.execute(
                    "SELECT body FROM snapshots WHERE id=?", (second["snapshots"][0],)
                ).fetchone()[0]
            )
            self.assertEqual(val["new_evidence_ids"], [])
            self.assertEqual(val["previous_snapshot"], first["snapshots"][0])

    def test_paper_record_rejects_claim_links_from_another_revision(self):
        with database(write=True) as db:
            a = self.record(
                db,
                "Alpha",
                "x",
                "v1",
                "result",
                "result",
                "2026-01-02T01:00:00+00:00",
                self.first,
            )
            b = self.record(
                db,
                "Alpha",
                "x",
                "v2",
                "updated result",
                "updated",
                "2026-01-03T01:00:00+00:00",
                self.second,
            )
            with self.assertRaises(ValueError):
                save_record(
                    db,
                    wid=a[0],
                    rid=b[1],
                    cid=a[2],
                    call_id=None,
                    analysis_id=None,
                    run_id=self.second,
                    question="bad",
                    focus="method",
                    heading=None,
                    start=0,
                    end=6,
                    topic="",
                    direction_ids=(),
                )

    def test_explicit_gap_reads_experiment_and_routes_new_record_once(self):
        from scholar_radar.review import review
        from scholar_radar.corrections import revise
        from scholar_radar.calls import invoke as actual_invoke
        from scholar_radar import calls

        text = "# 1 Introduction\nInitial premise.\n# 2 Experiments\nMatched controls reverse the finding.\n# 3 Limitations\nCoverage is local."
        with database(write=True) as db:
            wid, rid, cid, eid = self.record(
                db,
                "Retinal ablation",
                "gap",
                "v1",
                text,
                "Initial premise",
                "2026-01-03T04:00:00+00:00",
                self.second,
                targets=[self.did],
            )
            raw = store.DB.parent / "source.json"
            raw.write_text(
                json.dumps(
                    {
                        "document_id": "doc-1",
                        "document_revision": "gapv1",
                        "source": {"original_url": "https://example.com/gap"},
                    }
                )
            )
            db.execute(
                "INSERT INTO calls(id,service,tool,args,status,started_at,file) VALUES('get','analysis','get_paper_text','{}','done','2026-01-03',?)",
                (str(raw),),
            )
            db.execute("UPDATE revisions SET source_call='get' WHERE id=?", (rid,))
        with patch.object(assessment, "ask", new=AsyncMock(side_effect=answer)):
            before = asyncio.run(assessment.assess(self.run, [self.did]))["snapshots"][
                0
            ]
        verdict = {
            "reviews": [
                {
                    "id": "C1",
                    "verdict": "needs_evidence",
                    "reason": "缺少匹配的简单对照。",
                    "gap": {
                        "kind": "experiment",
                        "question": "匹配对照后仍成立吗？",
                        "anchor": eid,
                        "neighbor": "",
                    },
                }
            ]
        }
        with patch("scholar_radar.review.ask", new=AsyncMock(return_value=verdict)):
            asyncio.run(review(self.run))
        dispatched = []

        async def transport(args):
            dispatched.append(args)
            quote = "Matched controls reverse the finding."
            start = text.index(quote)
            return {
                "status": "success",
                "analysis_id": args["analysis_id"],
                "document_id": "doc-1",
                "document_revision": "gapv1",
                "analysis": {
                    "answer": "关键实验：在匹配对照中，结果反向。",
                    "question": args["question"],
                    "model_used": "fixture",
                    "coverage": {
                        "start": args["offset"],
                        "end": args["offset"] + args["limit_chars"],
                        "total_chars": len(text),
                    },
                    "evidence": [
                        {
                            "quote": quote,
                            "locations": [{"start": start, "end": start + len(quote)}],
                        }
                    ],
                },
            }

        async def record_transport(service, tool, args, **kwargs):
            return await actual_invoke(
                service, tool, args, transport=transport, **kwargs
            )

        with (
            patch("scholar_radar.readings.invoke", new=record_transport),
            patch.object(calls, "VAR", store.DB.parent),
        ):
            first = asyncio.run(revise(self.run))
            repeat = asyncio.run(revise(self.run))
        self.assertEqual(first["supplementation"]["attempted"], 1)
        self.assertEqual(repeat["supplementation"]["attempted"], 0)
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["offset"], text.index("# 2 Experiments"))
        with database() as db:
            q = db.execute(
                "SELECT status,record_id FROM research_gaps WHERE snapshot_id=?",
                (before,),
            ).fetchone()
            self.assertEqual(q["status"], "filled")
            self.assertNotEqual(q["record_id"], cid)
            self.assertTrue(
                any(
                    c["direction_id"] == self.did and c["version"] == q["record_id"]
                    for c in changes.pending(db)
                )
            )
            self.assertEqual(len(work_records(db, wid)), 2)
        self.run["evidence_cutoff"] = "2099-01-01T00:00:00+00:00"
        with patch.object(assessment, "ask", new=AsyncMock(side_effect=answer)):
            after = asyncio.run(assessment.assess(self.run))["snapshots"]
        self.assertNotIn(before, after)
        self.assertEqual(len(after), 1)
