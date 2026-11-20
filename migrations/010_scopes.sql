CREATE TABLE scope_versions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE scope_activations(id INTEGER PRIMARY KEY,scope_id TEXT NOT NULL REFERENCES scope_versions(id),at TEXT NOT NULL);
