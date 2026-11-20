import json
from .db import key
from .settings import ROOT,dump,now


def initialize(db):
    for d in json.loads((ROOT/"config/directions.json").read_text()):
        db.execute("INSERT OR IGNORE INTO directions VALUES(?,?,?,'tracking',?,?,?,'1',?)",
                   (d["id"],d["title"],d["layer"],d["question"],d["method"],d["setting"],now()))
    for f in json.loads((ROOT/"config/factors.json").read_text()):
        db.execute("INSERT OR IGNORE INTO factor_definitions VALUES(?,?,?,?,?,?)",
                   (f["id"],f["version"],f["target"],f["rule"],f["lifecycle"],dump(f)))
    for root,aliases in {"微软":["微软","Microsoft","微软亚洲研究院","MSRA"],"阿里":["阿里","阿里巴巴","通义","千问"],
                         "月之暗面":["月之暗面","Kimi"],"腾讯":["腾讯","混元"],"字节跳动":["字节","字节跳动","Seed","豆包","ByteDance"]}.items():
        oid=key("org",root)
        db.execute("INSERT OR IGNORE INTO organizations VALUES(?,?,NULL)",(oid,root))
        for alias in aliases:
            if alias=="MSRA" or alias=="微软亚洲研究院":
                team=key("org","Microsoft Research Asia")
                db.execute("INSERT OR IGNORE INTO organizations VALUES(?,?,?)",(team,"微软亚洲研究院",oid))
            else:
                team=oid
            db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)",(alias,team))
