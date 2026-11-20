import json
import tempfile
import unittest
from datetime import date,datetime,timezone
from pathlib import Path
from unittest.mock import patch

from scholar_radar import db as store
from scholar_radar.acquisition import coverage
from scholar_radar.classification import taxonomy
from scholar_radar.db import database,key,migrate
from scholar_radar.evidence import claim,resource,revision,span,work
from scholar_radar.factors import activity
from scholar_radar.feedback import feedback
from scholar_radar.profile import get_profile,save
from scholar_radar.queue import enqueue,schedule
from scholar_radar.registry import initialize
from scholar_radar.settings import ROOT,now


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        temp=ROOT/"_scratch"/"tmp"
        temp.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=temp)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        patcher=patch.object(store,"DB",self.root/"test.sqlite")
        patcher.start();self.addCleanup(patcher.stop)
        migrate()
        with database(write=True) as db:
            initialize(db)
            save(db,{"goals":["测试"],"assets":[],"target_companies":[],"compute":{}})


class Semantics(DatabaseCase):
    def test_external_ids_versions_and_shared_resource(self):
        with database(write=True) as db:
            a=work(db,"同一作品",{"arxiv":"2401.01234v1","doi":"https://doi.org/10.1/ABC"})
            self.assertEqual(a,work(db,"不同版本标题",{"arxiv":"2401.01234v2","doi":"10.1/abc"}))
            b=work(db,"同名或共享代码",{"s2":"another"})
            for w in (a,b): resource(db,w,"https://github.com/example/data","code")
            self.assertEqual(db.execute("SELECT count(*) FROM works").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT count(*) FROM resources").fetchone()[0],1)
            v1=revision(db,a,"https://arxiv.org/abs/2401.01234","paper","one","甲\n真实引文",version="v1")
            v2=revision(db,a,"https://arxiv.org/abs/2401.01234","paper","two","甲\n第二版本",version="v2")
            e=span(db,v1,2,6,"真实引文")
            self.assertNotEqual(v1,v2)
            with self.assertRaises(ValueError): span(db,v2,2,6,"真实引文")
            with self.assertRaises(ValueError): claim(db,"source_fact","无效位置",["x"],[e])
            self.assertEqual(db.execute("SELECT line_start FROM evidence WHERE id=?",(e,)).fetchone()[0],2)

    def test_observed_windows_exclude_discovery_and_late_backfill(self):
        with database(write=True) as db:
            version,_=taxonomy(db); rid=enqueue(db,"daily",date(2026,3,1)); did="tool-constraint"
            for i,stamp in enumerate(("2026-01-12","2026-02-14","2026-02-16")):
                w=work(db,str(i),{"s2":str(i)})
                db.execute("INSERT INTO observed VALUES('official','s',?,?,?,?)",(stamp,w,"v1",version))
                if i!=2: db.execute("INSERT INTO memberships VALUES(?,?,?,?,?)",(did,w,version,"[]",now()))
            work(db,"发现流单独命中",{"s2":"discovery-only"})
            self.assertIsNone(activity(db,did,"s","2026-03-01")[0])
            for start,end in [("2026-01-04","2026-02-01"),("2026-02-01","2026-02-15"),("2026-02-15","2026-03-01")]:
                coverage(db,rid,"official","observation","s","submitted",start,end,1,1,"ok",complete=True,classified=True)
            stats,_=activity(db,did,"s","2026-03-01")
            self.assertEqual([r["N"] for r in stats["windows"]],[1,2])
            self.assertEqual(stats["delta_pp"],-50)
            db.execute("UPDATE observed SET membership_version=NULL WHERE work_id=?",(w,))
            self.assertIsNone(activity(db,did,"s","2026-03-01")[0])

    def test_profile_revert_and_scheduled_manual_dedup(self):
        with database(write=True) as db:
            a=get_profile(db); day=date(2026,11,21); rid=enqueue(db,"daily",day)
            self.assertEqual(rid,enqueue(db,"daily",day))
            b={**a,"daily_limit":1}; save(db,b); restored=save(db,a)
            self.assertNotEqual(restored,a["id"])
            schedule(db,datetime(2026,11,21,1,0,tzinfo=timezone.utc))
            self.assertEqual(db.execute("SELECT count(*) FROM runs WHERE as_of=? AND kind='daily'",(str(day),)).fetchone()[0],1)

    def test_reading_does_not_imply_usefulness(self):
        with database(write=True) as db:
            w=work(db,"标题",{"s2":"test"})
            for _ in range(2): feedback(db,"work",w,"reading_status","read","", "same-client-event")
            self.assertEqual(db.execute("SELECT count(*) FROM feedback").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM feedback WHERE dimension='reading_value'").fetchone()[0],0)
