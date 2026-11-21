-- A paper analysis is identified by its original paper claim and fixed revision.
CREATE TABLE reading_records(
    id TEXT PRIMARY KEY REFERENCES claims(id),
    work_id TEXT NOT NULL REFERENCES works(id),
    revision_id TEXT NOT NULL REFERENCES revisions(id),
    analysis_id TEXT, call_id TEXT REFERENCES calls(id),
    question TEXT NOT NULL, focus TEXT NOT NULL, heading TEXT,
    start INTEGER NOT NULL, end INTEGER NOT NULL, recorded_at TEXT NOT NULL,
    sections TEXT NOT NULL DEFAULT '{}', topic TEXT NOT NULL DEFAULT '',
    CHECK(start >= 0 AND end > start)
);
CREATE UNIQUE INDEX reading_record_analysis ON reading_records(analysis_id) WHERE analysis_id IS NOT NULL;
CREATE INDEX reading_record_work ON reading_records(work_id,revision_id,recorded_at);
CREATE TABLE reading_record_runs(
    record_id TEXT REFERENCES reading_records(id),run_id TEXT REFERENCES runs(id),
    PRIMARY KEY(record_id,run_id)
);
CREATE TABLE reading_record_directions(
    record_id TEXT REFERENCES reading_records(id),direction_id TEXT REFERENCES directions(id),
    origin TEXT NOT NULL, PRIMARY KEY(record_id,direction_id)
);
CREATE TABLE direction_assessment_inputs(
    direction_id TEXT REFERENCES directions(id),profile_id TEXT REFERENCES profiles(id),signature TEXT,
    run_id TEXT REFERENCES runs(id),checked_at TEXT NOT NULL,
    PRIMARY KEY(direction_id,profile_id,signature)
);
CREATE TABLE snapshot_reading_records(
    snapshot_id TEXT REFERENCES snapshots(id),record_id TEXT REFERENCES reading_records(id),
    PRIMARY KEY(snapshot_id,record_id)
);
CREATE TABLE research_gaps(
    id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL REFERENCES snapshots(id),direction_id TEXT NOT NULL REFERENCES directions(id),
    work_id TEXT REFERENCES works(id),revision_id TEXT REFERENCES revisions(id),kind TEXT NOT NULL,question TEXT NOT NULL,
    status TEXT NOT NULL,record_id TEXT REFERENCES reading_records(id),details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX research_gaps_snapshot ON research_gaps(snapshot_id,status);

-- A successful reading outcome is the only legacy pointer to a paper-specific
-- claim. Older direction inferences can share its works and quotes.
CREATE TEMP VIEW verified_legacy_outcomes AS
WITH outcomes(run_id,paper,result,focus,finished) AS (
    SELECT l.run_id,l.paper,l.outcome,coalesce(json_extract(l.paper,'$.evidence_focus'),'overview'),
           coalesce(r.ended_at,r.started_at,r.created_at)
        FROM readings l JOIN runs r ON r.id=l.run_id WHERE l.status='done'
    UNION ALL
    SELECT j.run_id,l.paper,j.outcome,coalesce(json_extract(j.payload,'$.focus'),json_extract(l.paper,'$.evidence_focus'),'overview'),
           coalesce(j.lease_at,r.ended_at,r.started_at,r.created_at)
        FROM jobs j JOIN runs r ON r.id=j.run_id JOIN readings l
          ON l.run_id=j.run_id AND l.work_key=json_extract(j.payload,'$.key')
        WHERE j.status='done' AND j.stage='read' AND json_valid(j.outcome)
)
SELECT o.run_id,c.id claim_id,d.work_id,v.id revision_id,c.conditions,o.focus,o.finished,
       coalesce(json_extract(o.paper,'$.theme_hint'),'') topic,
       json_extract(c.conditions,'$.coverage.start') start,json_extract(c.conditions,'$.coverage.end') end
FROM outcomes o JOIN claims c ON c.id=json_extract(o.result,'$.claim_id')
JOIN revisions v ON v.id=json_extract(o.result,'$.revision_id') AND v.id=json_extract(c.conditions,'$.revision')
JOIN documents d ON d.id=v.document_id AND d.kind='paper' AND d.work_id=json_extract(o.result,'$.work_id')
WHERE c.kind='system_inference' AND json_type(c.conditions,'$.question')='text'
  AND json_type(c.conditions,'$.coverage.start')='integer' AND json_type(c.conditions,'$.coverage.end')='integer'
  AND json_extract(c.conditions,'$.coverage.start')>=0 AND json_extract(c.conditions,'$.coverage.end')<=v.total_chars
  AND json_extract(c.conditions,'$.coverage.end')>json_extract(c.conditions,'$.coverage.start')
  AND EXISTS(SELECT 1 FROM claim_evidence ce WHERE ce.claim_id=c.id)
  AND NOT EXISTS(SELECT 1 FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id
       WHERE ce.claim_id=c.id AND (e.revision_id!=v.id OR e.start<json_extract(c.conditions,'$.coverage.start') OR e.end>json_extract(c.conditions,'$.coverage.end')))
  AND NOT EXISTS(SELECT ce.evidence_id FROM claim_evidence ce WHERE ce.claim_id=c.id
       EXCEPT SELECT value FROM json_each(o.result,'$.evidence_ids'))
  AND NOT EXISTS(SELECT value FROM json_each(o.result,'$.evidence_ids')
       EXCEPT SELECT ce.evidence_id FROM claim_evidence ce WHERE ce.claim_id=c.id);
INSERT OR IGNORE INTO reading_records(id,work_id,revision_id,question,focus,start,end,recorded_at,topic)
 SELECT claim_id,work_id,revision_id,json_extract(conditions,'$.question'),focus,start,end,min(finished),topic
 FROM verified_legacy_outcomes GROUP BY claim_id;
INSERT OR IGNORE INTO reading_record_runs SELECT claim_id,run_id FROM verified_legacy_outcomes;
DROP VIEW verified_legacy_outcomes;
INSERT OR IGNORE INTO reading_record_directions
 SELECT r.id,m.direction_id,'existing_membership' FROM reading_records r JOIN memberships m ON m.work_id=r.work_id;

CREATE VIRTUAL TABLE reading_search USING fts5(record_id UNINDEXED,work_id UNINDEXED,title,topic,analysis,abstract,tokenize='unicode61');
INSERT INTO reading_search SELECT r.id,w.id,w.title,r.topic,c.statement,coalesce(json_extract(w.metadata,'$.abstract'),'')
  FROM reading_records r JOIN works w ON w.id=r.work_id JOIN claims c ON c.id=r.id;
CREATE TRIGGER reading_search_insert AFTER INSERT ON reading_records BEGIN
 INSERT INTO reading_search SELECT NEW.id,w.id,w.title,NEW.topic,c.statement,coalesce(json_extract(w.metadata,'$.abstract'),'')
   FROM works w JOIN claims c ON c.id=NEW.id WHERE w.id=NEW.work_id;
END;
