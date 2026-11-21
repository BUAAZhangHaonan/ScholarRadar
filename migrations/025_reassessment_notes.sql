CREATE TABLE reassessment_notes(
    direction_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    snapshot_id TEXT REFERENCES snapshots(id),
    reasoning TEXT NOT NULL,
    input_changes TEXT NOT NULL,
    PRIMARY KEY (direction_id,profile_id,signature),
    FOREIGN KEY (direction_id,profile_id,signature)
      REFERENCES direction_assessment_inputs(direction_id,profile_id,signature)
);
CREATE INDEX reassessment_snapshot ON reassessment_notes(snapshot_id);
