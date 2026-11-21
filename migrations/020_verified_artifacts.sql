CREATE TABLE verified_artifacts(id TEXT PRIMARY KEY,resource_id TEXT NOT NULL REFERENCES resources(id),kind TEXT NOT NULL,path TEXT NOT NULL,version TEXT NOT NULL,url TEXT NOT NULL,source_url TEXT NOT NULL,evidence_id TEXT NOT NULL REFERENCES evidence(id),first_verified_at TEXT NOT NULL,last_verified_at TEXT NOT NULL);
CREATE INDEX artifacts_by_resource ON verified_artifacts(resource_id,kind);
