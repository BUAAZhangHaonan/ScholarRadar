"""Freeze the selected snapshot and the contiguous source passages actually read."""
import json
from .db import key,rows
from .profile import get_profile
from .settings import dump


def selected_bundle(db,did,sid,stage,focus,previous_idea=None):
    s=db.execute("SELECT s.*,d.title AS direction_title FROM snapshots s JOIN directions d ON d.id=s.dir_id WHERE s.id=? AND s.dir_id=?",(sid,did)).fetchone()
    if not s: raise ValueError("该快照不属于选择的方向")
    profile=get_profile(db)
    b=json.loads(s["body"])
    citations=rows(db,"""SELECT e.id,e.start,e.end,e.quote,v.id revision_id,v.body,v.total_chars,v.version,v.upstream_revision,
        d.url,d.kind,d.work_id,w.title FROM snapshot_evidence se JOIN evidence e ON e.id=se.evidence_id
        JOIN revisions v ON v.id=e.revision_id JOIN documents d ON d.id=v.document_id LEFT JOIN works w ON w.id=d.work_id
        WHERE se.snapshot_id=? ORDER BY d.id,e.start""",(sid,))
    if not citations: raise ValueError("当前快照尚无可传入的原始材料")
    sources=[];notes=[]; included_records=set()
    for e in citations:
        if e["body"][e["start"]:e["end"]]!=e["quote"]: raise ValueError("来源片段与固定修订不匹配")
        # Preserve one contiguous interval per source and its offsets in the parser's representation.
        start=max(0,e["start"]-220); end=min(len(e["body"]),e["end"]+220)
        content=e["body"][start:end]
        url=e["url"]
        if e["version"] and "arxiv.org/abs/" in url and not url.endswith(e["version"]): url+=e["version"]
        sources.append({"external_source_id":e["id"],"title":e["title"] or ("官方岗位详情" if e["kind"]=="job" else "已核验材料"),
            "url":url,"version":e["version"] or e["upstream_revision"],"revision_id":e["revision_id"],
            "work_id":e["work_id"],"evidence_ids":[e["id"]],"access":"passage","content":content,
            "start_char":start,"total_chars":e["total_chars"],"source_type":"paper" if e["kind"]=="paper" else "official_documentation"})
        rs=rows(db,"""SELECT rr.id,rr.question,rr.start,rr.end,c.statement FROM reading_records rr JOIN claims c ON c.id=rr.id
             JOIN claim_evidence ce ON ce.claim_id=rr.id WHERE rr.revision_id=? AND ce.evidence_id=? ORDER BY rr.recorded_at DESC""",
             (e["revision_id"],e["id"]))
        for note in rs:
            if note["id"] in included_records: continue
            included_records.add(note["id"])
            notes.append({"external_source_id":e["id"],"access":"passage","finding":note["statement"],"relevance":note["question"],
                          "limits":f"既有阅读笔记针对该修订字符区间 [{note['start']}, {note['end']})；所附原文为其中的固定引文片段。"})
    nearest=b.get("nearest") or ""
    if isinstance(nearest,dict): nearest=nearest.get("difference") or nearest.get("title") or ""
    forecast=b.get("forecast") or {}
    proposal={"title":b.get("title") or s["direction_title"],"question":b.get("question") or s["direction_title"],
              "hypothesis":forecast.get("hypothesis") or b.get("judgment") or focus,
              "expected_value":b.get("judgment") or b.get("change") or focus,
              "claimed_difference":nearest or "目前与最近邻的差异待核对。",
              "decisive_unknown":b.get("limitation") or forecast.get("refute") or focus}
    payload={"schema_version":"radar.arc.selected-idea.v1","origin":{"system":"ScholarRadar","direction_id":did,
              "snapshot_id":sid,"profile_id":profile["id"]},"request":{"stage":stage,"focus":focus,
              "boundaries":["本次仅开展论文和研究设计预研；已核验的原文、既有阅读笔记和研究假设分别使用。"]},
              "proposal":proposal,"sources":sources,"source_notes":notes,"assets":profile["assets"],
              "profile":{"goals":profile["goals"],"validation_weeks":profile["validation_weeks"],"active_limit":profile["active_limit"],
                         "research_weights":profile["research_weights"],"snapshot_profile_id":s["profile_id"]},
              "resource_conditions":profile["compute"]}
    if previous_idea: payload["idea_id"]=previous_idea
    # Stable across repeated clicks even when the library later receives more independent notes.
    hid=key("arc-handoff-v1",did,sid,profile["id"],stage,focus,previous_idea)
    return hid,{**payload,"handoff_id":hid}
