CREATE VIRTUAL TABLE reading_term_frequencies USING fts5vocab(reading_search,'row');
CREATE VIRTUAL TABLE reading_phrases USING fts5(record_id UNINDEXED,topic,analysis,tokenize='trigram');
INSERT INTO reading_phrases SELECT r.id,r.topic,c.statement FROM reading_records r JOIN claims c ON c.id=r.id;
CREATE TRIGGER reading_phrase_insert AFTER INSERT ON reading_records BEGIN
 INSERT INTO reading_phrases SELECT NEW.id,NEW.topic,statement FROM claims WHERE id=NEW.id;
END;
