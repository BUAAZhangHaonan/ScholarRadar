CREATE TABLE selection_material(run_id TEXT REFERENCES runs(id),work_id TEXT REFERENCES works(id),material TEXT NOT NULL,PRIMARY KEY(run_id,work_id));
