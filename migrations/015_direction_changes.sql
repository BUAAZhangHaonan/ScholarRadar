CREATE TABLE direction_changes(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, entity_id TEXT NOT NULL, version TEXT NOT NULL,
 direction_id TEXT NOT NULL, created_at TEXT NOT NULL, handled_at TEXT,
 UNIQUE(kind,entity_id,version,direction_id)
);
CREATE INDEX unhandled_direction_changes ON direction_changes(direction_id,handled_at,created_at);
