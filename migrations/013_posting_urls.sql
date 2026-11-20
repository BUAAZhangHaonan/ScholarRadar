CREATE TABLE posting_urls(url TEXT PRIMARY KEY,posting_id TEXT NOT NULL REFERENCES postings(id));
INSERT INTO posting_urls SELECT url,id FROM postings;
CREATE UNIQUE INDEX posting_official_identity ON postings(organization_id,official_id) WHERE official_id IS NOT NULL;
