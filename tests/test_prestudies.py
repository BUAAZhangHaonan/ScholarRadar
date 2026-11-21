import asyncio
import json
from datetime import date
from unittest.mock import patch

from test_semantics import DatabaseCase
from scholar_radar.db import database
from scholar_radar.evidence import revision, span, work
from scholar_radar.prestudy_api import QUERY, Selection, enqueue_selection, present
from scholar_radar.prestudy_worker import execute, save_result
from scholar_radar.profile import get_profile, save
from scholar_radar.queue import enqueue
from scholar_radar.settings import dump, now


class SelectedIdea(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.direction = "pre-generation-risk"
        self.selection = Selection(snapshot_id="snapshot-a", stage="develop", focus="哪一项对照能区分两种解释？", request_id="click-a")
        with database(write=True) as db:
            rid = enqueue(db, "daily", date(2026, 11, 20))
            self.profile = get_profile(db)["id"]
            wid = work(db, "对照研究", {"arxiv": "2201.12345"})
            revision_id = revision(db, wid, "https://arxiv.org/abs/2201.12345", "paper", "fixed", "引文与实验条件", version="v2")
            evidence = span(db, revision_id, 0, 2, "引文")
            db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)", ("snapshot-a", self.direction, rid, now(), now(), self.profile, "scope", "1", dump({"title":"对照","question":"具体问题"}), "inputs"))
            db.execute("INSERT INTO snapshot_evidence VALUES(?,?)", ("snapshot-a", evidence))
        self.runtime = patch("scholar_radar.prestudy_api.runtime", return_value={"data_dir": "fixture"})
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def submit(self, selection=None):
        with database(write=True) as db:
            return enqueue_selection(db, self.direction, selection or self.selection)

    def test_double_click_and_profile_edits_preserve_original_request(self):
        first = self.submit()
        other = self.submit(self.selection.model_copy(update={"request_id":"other-click"}))
        self.assertTrue(other["reused"])
        self.assertEqual(first["task_id"], other["task_id"])
        with database(write=True) as db:
            save(db, {**get_profile(db), "goals":["新问题"]})
        self.assertEqual(self.submit()["id"], first["id"])
        with self.assertRaises(ValueError):
            self.submit(self.selection.model_copy(update={"focus":"另一问题"}))
        with database() as db:
            frozen = json.loads(db.execute("SELECT bundle_json FROM arc_handoffs WHERE id=?", (first["id"],)).fetchone()[0])
            self.assertEqual(frozen["origin"]["profile_id"], self.profile)
            self.assertEqual(frozen["sources"][0]["url"], "https://arxiv.org/abs/2201.12345v2")
            self.assertEqual(frozen["sources"][0]["content"], "引文与实验条件")
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE stage='arc_stage'").fetchone()[0], 1)

    def test_recover_same_native_stage_and_keep_draft_and_external_sources(self):
        action = self.submit()
        hid = action["id"]
        origin = {"system":"ScholarRadar", "direction_id":self.direction, "snapshot_id":"snapshot-a", "profile_id":self.profile}
        native = {"handoff_id":hid, "stage":"develop", "focus":self.selection.focus, "idea_id":"actual-idea", "run_id":"actual-run",
                  "origin":origin, "execution_status":"prepared"}
        save_result(hid,native)
        with self.assertRaises(ValueError):
            save_result(hid,{**native, "idea_id":"a-different-idea"})
        with self.assertRaises(ValueError):
            save_result(hid,{**native, "origin":{**origin, "profile_id":"unrelated"}})
        calls = []
        async def native_result(config, operation, submitted_id, stdin=None):
            self.assertEqual(submitted_id,hid)
            calls.append(operation)
            if operation == "result":
                return native
            return {**native,"execution_status":"completed","research_decision":"lead","current_understanding":"当前证据只支持较窄条件",
                    "evidence_limited":True,"presentation_status":"draft","polish_failure":"未取得成文结果",
                    "draft_text":"保留的研究原稿","source_directory":[{"id":"new-paper","url":"https://example.org/paper"}],
                    "source_mapping":{"new-paper":"native-source"},"cited_source_ids":["new-paper"]}
        with patch("scholar_radar.prestudy_worker.command",native_result):
            asyncio.run(execute({},{"handoff_id":hid}))
            self.assertTrue(asyncio.run(execute({},{"handoff_id":hid}))["reused"])
        self.assertEqual(calls, ["result","execute"])
        with database() as db:
            obj = present(db.execute(QUERY+" WHERE h.id=?",(hid,)).fetchone())
            self.assertTrue(obj["evidence_limited"])
            self.assertEqual((obj["research_decision"],obj["draft_text"],obj["sources"][0]["id"]),("lead","保留的研究原稿","new-paper"))
            self.assertEqual((obj["presentation_status"], obj["polish_failure"]), ("draft", "未取得成文结果"))
            self.assertEqual(db.execute("SELECT count(*) FROM direction_changes WHERE kind='arc_result'").fetchone()[0],1)
        next_task = self.submit(self.selection.model_copy(update={"idea_id":"actual-idea","stage":"run","request_id":"stage-two"}))
        self.assertNotEqual(next_task["id"],hid)
        with self.assertRaises(ValueError):
            self.submit(self.selection.model_copy(update={"idea_id":"another-idea","stage":"run","request_id":"unlinked"}))
