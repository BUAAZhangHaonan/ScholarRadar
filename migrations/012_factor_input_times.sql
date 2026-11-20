CREATE TABLE factor_input_times(kind TEXT,entity TEXT,related TEXT,at TEXT NOT NULL,PRIMARY KEY(kind,entity,related));
CREATE TRIGGER evidence_clock AFTER INSERT ON evidence BEGIN
 INSERT OR IGNORE INTO factor_input_times VALUES('evidence',NEW.id,'',strftime('%Y-%m-%dT%H:%M:%S+00:00','now')); END;
CREATE TRIGGER resource_clock AFTER INSERT ON work_resources BEGIN
 INSERT OR IGNORE INTO factor_input_times VALUES('resource',NEW.work_id,NEW.resource_id,strftime('%Y-%m-%dT%H:%M:%S+00:00','now')); END;
CREATE TRIGGER evaluation_clock AFTER INSERT ON evaluations BEGIN
 INSERT OR IGNORE INTO factor_input_times VALUES('evaluation',NEW.id,'',strftime('%Y-%m-%dT%H:%M:%S+00:00','now')); END;
INSERT OR IGNORE INTO factor_input_times SELECT 'evidence',id,'',strftime('%Y-%m-%dT%H:%M:%S+00:00','now') FROM evidence;
INSERT OR IGNORE INTO factor_input_times SELECT 'resource',work_id,resource_id,strftime('%Y-%m-%dT%H:%M:%S+00:00','now') FROM work_resources;
INSERT OR IGNORE INTO factor_input_times SELECT 'evaluation',e.id,'',r.created_at FROM evaluations e JOIN runs r ON r.id=e.run_id;
