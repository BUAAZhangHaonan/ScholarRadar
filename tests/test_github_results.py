import asyncio
import base64
import hashlib
import json
from datetime import date, datetime, UTC
from unittest import TestCase
from unittest.mock import patch

import httpx

from test_semantics import DatabaseCase
from scholar_radar import github_results as github
from scholar_radar.db import database, key
from scholar_radar.queue import enqueue, resume, schedule, take
from scholar_radar.settings import dump


CONFIG = {"enabled": True, "repository": "example/research-results", "branch": "main"}


class FakeGitHub:
    """In-memory Git trees: exercise atomic updates and lost acknowledgements."""

    def __init__(self):
        self.private = True
        self.head = "initial"
        self.trees = {"initial-tree": {"README.md": "existing repository"}}
        self.commits = {"initial": {"tree": {"sha": "initial-tree"}}}
        self.writes = []
        self.lose_ack = False
        self.conflict = False

    @property
    def files(self):
        return self.trees[self.commits[self.head]["tree"]["sha"]]

    def handle(self, request):
        path = request.url.path.removeprefix("/repos/example/research-results")
        data = json.loads(request.content) if request.content else None
        if request.method != "GET":
            self.writes.append((request.method, path, data))
        if path == "":
            result = {"private": self.private, "default_branch": "main"}
        elif path == "/git/ref/heads/main":
            result = {"object": {"sha": self.head}}
        elif path.startswith("/git/commits/"):
            result = self.commits[path.rsplit("/", 1)[1]]
        elif path.startswith("/contents/"):
            head = request.url.params["ref"]
            files = self.trees[self.commits[head]["tree"]["sha"]]
            text = files.get(path.removeprefix("/contents/"))
            if text is None:
                return httpx.Response(404)
            result = {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
        elif path == "/git/trees":
            files = dict(self.trees[data["base_tree"]])
            files.update({x["path"]: x["content"] for x in data["tree"]})
            sha = hashlib.sha256(dump(files).encode()).hexdigest()
            self.trees[sha] = files
            result = {"sha": sha}
        elif path == "/git/commits":
            sha = f"commit-{len(self.commits)}"
            self.commits[sha] = {"tree": {"sha": data["tree"]}, "parents": data["parents"]}
            result = {"sha": sha}
        elif path == "/git/refs/heads/main":
            assert data["force"] is False
            if self.conflict:
                self.conflict = False
                self.trees["concurrent-tree"] = {**self.files, "notes.md": "concurrent edit"}
                self.commits["concurrent"] = {"tree": {"sha": "concurrent-tree"}}
                self.head = "concurrent"
                return httpx.Response(422)
            assert self.commits[data["sha"]]["parents"] == [self.head]
            self.head = data["sha"]
            if self.lose_ack:
                self.lose_ack = False
                raise httpx.ReadTimeout("lost acknowledgement", request=request)
            result = {"object": {"sha": self.head}}
        else:
            raise AssertionError((request.method, path))
        return httpx.Response(200, json=result)

    async def publish(self, entry, body):
        async with httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(self.handle)) as client:
            return await github.commit_result(client, CONFIG, entry, body)


def entry(result_id, day="2026-11-21", hour="10"):
    return {"id": "report:" + result_id, "kind": "daily", "date": day,
            "generated_at": f"{day}T{hour}:00:00+00:00", "title": day + " 日报",
            "path": f"results/daily/{day}-{result_id}.md"}


class GitPublishing(TestCase):
    def test_versions_latest_and_recovery_after_lost_success_response(self):
        remote = FakeGitHub()
        first, second, old = entry("one"), entry("two", hour="11"), entry("old", "2026-11-19")
        remote.lose_ack = True
        with self.assertRaises(github.GitHubSyncUnavailable):
            asyncio.run(remote.publish(first, "# first judgement\n"))
        self.assertTrue(asyncio.run(remote.publish(first, "# first judgement\n"))["reused"])
        self.assertEqual(len([w for w in remote.writes if w[1] == "/git/commits"]), 1)
        asyncio.run(remote.publish(second, "# revised judgement\n"))
        asyncio.run(remote.publish(old, "# historical judgement\n"))
        self.assertEqual(remote.files["README.md"], "existing repository")
        self.assertEqual(remote.files[first["path"]], "# first judgement\n")
        self.assertEqual(remote.files[second["path"]], "# revised judgement\n")
        latest = remote.files["results/LATEST.md"]
        self.assertIn("# revised judgement", latest)
        self.assertNotIn("# historical judgement", latest)
        self.assertEqual(len(json.loads(remote.files["results/index.json"])["entries"]), 3)

    def test_concurrent_edit_is_preserved_on_retry(self):
        remote = FakeGitHub()
        remote.conflict = True
        with self.assertRaises(github.GitHubSyncUnavailable):
            asyncio.run(remote.publish(entry("one"), "# saved\n"))
        asyncio.run(remote.publish(entry("one"), "# saved\n"))
        self.assertEqual(remote.files["notes.md"], "concurrent edit")
        self.assertEqual(remote.files[entry("one")["path"]], "# saved\n")

    def test_public_repository_is_rejected_before_any_write(self):
        remote = FakeGitHub()
        remote.private = False
        with self.assertRaisesRegex(ValueError, "私有仓库"):
            asyncio.run(remote.publish(entry("one"), "private research"))
        self.assertEqual(remote.writes, [])


class ResultQueue(DatabaseCase):
    def setUp(self):
        super().setUp()
        cfg = patch.object(github, "configuration", return_value=CONFIG)
        cfg.start()
        self.addCleanup(cfg.stop)

    def store_reports(self, db):
        rid = enqueue(db, "daily", date(2026, 11, 19))
        report_id = key(rid, "daily")
        for result_id, summary in (("first", "最初判断"), ("second", "后续判断")):
            body = {"kind": "daily", "date": "2026-11-19", "generated_at": "2026-11-19T03:00:00+00:00",
                    "snapshot_id": result_id, "directions": [], "editorial": {"summary": summary}}
            db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                       (report_id, rid, "daily", body["date"], dump(body), body["generated_at"]))
            db.execute("INSERT INTO report_versions VALUES(?,?,?,?)", (result_id, report_id, body["generated_at"], dump(body)))
        db.execute("UPDATE jobs SET status='done' WHERE run_id=?", (rid,))
        db.execute("UPDATE runs SET status='done' WHERE id=?", (rid,))
        return rid

    def test_backfill_wakes_finished_runs_and_exports_each_frozen_version(self):
        with database(write=True) as db:
            rid = self.store_reports(db)
            self.assertEqual(github.backfill(db), {"reports": 2, "arc_results": 0})
            github.backfill(db)
            jobs = list(db.execute("SELECT * FROM jobs WHERE stage='github_sync'"))
            self.assertEqual(len(jobs), 2)
            pair = take(db, "test-worker")
            self.assertEqual(pair[1]["stage"], "github_sync")
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE run_id=? AND stage!='github_sync' AND status!='done'", (rid,)).fetchone()[0], 0)
        by_id = {json.loads(j["payload"])["result_id"]: json.loads(j["payload"]) for j in jobs}
        self.assertIn("最初判断", github.saved_result(by_id["first"])[1])
        self.assertNotIn("后续判断", github.saved_result(by_id["first"])[1])
        self.assertIn("后续判断", github.saved_result(by_id["second"])[1])
        versions = [github.saved_result(by_id[name])[0] for name in ("first", "second")]
        self.assertEqual(github.ordered(versions)[0]["id"], "report:second")

    def test_upload_retry_does_not_repeat_research_even_for_old_arc_run(self):
        with database(write=True) as db:
            rid = self.store_reports(db)
            jid = github.enqueue_result(db, rid, "report", "first")
            db.execute("UPDATE runs SET kind='arc',status='partial' WHERE id=?", (rid,))
            db.execute("UPDATE jobs SET status='failed',attempts=1,lease_at=?,outcome=? WHERE id=?",
                       ("2026-11-19T03:00:00+00:00", dump({"error_type": "GitHubSyncUnavailable"}), jid))
            self.assertEqual(resume(db, rid), ["github_sync"])
            db.execute("UPDATE jobs SET status='failed' WHERE id=?", (jid,))
            db.execute("UPDATE runs SET status='partial' WHERE id=?", (rid,))
            schedule(db, datetime(2026, 11, 21, 8, tzinfo=UTC), limit=1)
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0], "queued")
            self.assertEqual(db.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()[0], "queued")
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE run_id=? AND stage!='github_sync' AND status!='done'", (rid,)).fetchone()[0], 0)

    def test_publish_enqueues_the_saved_snapshot_and_disabled_adds_no_job(self):
        from scholar_radar.reports import publish

        with database(write=True) as db:
            rid = enqueue(db, "daily", date(2026, 11, 21))
            run = dict(db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE stage='github_sync'").fetchone()[0], 0)
        with patch("scholar_radar.reports.ROOT", self.root):
            asyncio.run(publish(run))
        with database(write=True) as db:
            payload = json.loads(db.execute("SELECT payload FROM jobs WHERE stage='github_sync'").fetchone()[0])
            self.assertEqual(payload["result_id"], db.execute("SELECT id FROM report_versions").fetchone()[0])
            with patch.object(github, "configuration", return_value={}):
                self.assertIsNone(github.enqueue_result(db, rid, "report", "disabled"))
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE stage='github_sync'").fetchone()[0], 1)
            db.execute("UPDATE jobs SET status='failed',outcome=? WHERE stage='github_sync'", (dump({"error_type": "GitHubSyncUnavailable"}),))
        with patch("scholar_radar.reports.ROOT", self.root):
            asyncio.run(publish(run))
        with database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM report_versions").fetchone()[0], 1)
