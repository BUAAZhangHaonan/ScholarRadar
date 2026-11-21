CREATE TABLE arc_handoffs(
 id TEXT PRIMARY KEY,direction_id TEXT NOT NULL REFERENCES directions(id),snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
 profile_id TEXT NOT NULL REFERENCES profiles(id),stage TEXT NOT NULL CHECK(stage IN ('develop','run')),focus TEXT NOT NULL,
 idea_id TEXT,arc_run_id TEXT,radar_run_id TEXT NOT NULL REFERENCES runs(id),job_id TEXT NOT NULL REFERENCES jobs(id),
 status TEXT NOT NULL,bundle_json TEXT NOT NULL,runtime_json TEXT NOT NULL,result_json TEXT,error TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX handoffs_by_direction ON arc_handoffs(direction_id,created_at);
CREATE TABLE arc_requests(request_id TEXT PRIMARY KEY,handoff_id TEXT NOT NULL REFERENCES arc_handoffs(id));
