CREATE TABLE report_versions(id TEXT PRIMARY KEY,report_id TEXT NOT NULL REFERENCES reports(id),generated_at TEXT NOT NULL,body TEXT NOT NULL);
INSERT OR IGNORE INTO report_versions SELECT json_extract(body,'$.snapshot_id'),id,generated_at,body FROM reports;
