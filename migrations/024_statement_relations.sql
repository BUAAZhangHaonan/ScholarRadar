CREATE TABLE direction_evidence_relations(
 snapshot_id TEXT NOT NULL REFERENCES snapshots(id),work_id TEXT NOT NULL REFERENCES works(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id),assertion TEXT NOT NULL,conditions TEXT NOT NULL,
 relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','qualifies')),
 PRIMARY KEY(snapshot_id,evidence_id,assertion,conditions,relation)
);
CREATE INDEX direction_evidence_by_work ON direction_evidence_relations(work_id,relation);
