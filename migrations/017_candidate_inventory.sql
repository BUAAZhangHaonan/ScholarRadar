CREATE TABLE candidate_inventory(work_id TEXT PRIMARY KEY REFERENCES works(id),first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,version TEXT NOT NULL,body TEXT NOT NULL);
INSERT INTO candidate_inventory SELECT id,first_seen,first_seen,'imported',metadata FROM works;
CREATE TABLE candidate_decisions(work_id TEXT REFERENCES works(id),profile_id TEXT REFERENCES profiles(id),scope TEXT,version TEXT,run_id TEXT REFERENCES runs(id),result TEXT NOT NULL,reason TEXT NOT NULL,at TEXT NOT NULL,PRIMARY KEY(work_id,profile_id,scope,version));
CREATE INDEX candidate_pool_order ON candidate_inventory(first_seen,work_id);
