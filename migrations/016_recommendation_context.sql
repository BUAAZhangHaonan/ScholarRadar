CREATE TABLE recommendation_contexts(
 id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
 snapshot_id TEXT REFERENCES snapshots(id), evaluation_id TEXT REFERENCES evaluations(id),
 profile_id TEXT REFERENCES profiles(id), recorded_at TEXT NOT NULL, origin TEXT NOT NULL,
 reason TEXT NOT NULL, features TEXT NOT NULL, used_feedback TEXT NOT NULL);
CREATE INDEX recommendations_by_object ON recommendation_contexts(entity_type,entity_id,recorded_at);
CREATE TABLE feedback_contexts(feedback_id TEXT PRIMARY KEY REFERENCES feedback(id),
 recommendation_id TEXT REFERENCES recommendation_contexts(id),snapshot_id TEXT REFERENCES snapshots(id),
 action_id TEXT REFERENCES actions(id),context TEXT NOT NULL);
CREATE TABLE outcome_contexts(event_id TEXT PRIMARY KEY REFERENCES action_events(id),
 snapshot_id TEXT NOT NULL REFERENCES snapshots(id),work_ids TEXT NOT NULL,feedback_ids TEXT NOT NULL);
