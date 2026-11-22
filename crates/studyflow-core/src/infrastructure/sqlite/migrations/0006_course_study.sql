CREATE TABLE course_study_sessions (
    id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    revision INTEGER DEFAULT '1' NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    new_version BOOLEAN DEFAULT 0 NOT NULL,
    snapshot_json TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    progress_json TEXT DEFAULT '{}' NOT NULL,
    resume_lesson_id VARCHAR(36),
    version INTEGER DEFAULT '1' NOT NULL,
    reading_completed BOOLEAN DEFAULT 0 NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_course_study_revision UNIQUE (course_id, revision),
    FOREIGN KEY(course_id) REFERENCES courses (id),
    UNIQUE (idempotency_key)
);

CREATE INDEX ix_course_study_sessions_course_id ON course_study_sessions (course_id);

ALTER TABLE submissions ADD COLUMN study_session_id VARCHAR(36);

CREATE INDEX ix_submissions_study_session_id ON submissions (study_session_id);

ALTER TABLE submissions ADD COLUMN batch_id VARCHAR(36);

CREATE INDEX ix_submissions_batch_id ON submissions (batch_id);

ALTER TABLE course_write_receipts ADD COLUMN study_session_id VARCHAR(36);

CREATE INDEX ix_course_write_receipts_study_session_id ON course_write_receipts (study_session_id);
