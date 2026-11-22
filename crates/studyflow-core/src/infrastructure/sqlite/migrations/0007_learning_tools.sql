CREATE TABLE _alembic_tmp_event_logs (
    id VARCHAR(36) NOT NULL,
    source VARCHAR(32) NOT NULL,
    object_type VARCHAR(40) NOT NULL,
    object_id VARCHAR(36) NOT NULL,
    action VARCHAR(80) NOT NULL,
    summary TEXT DEFAULT ('') NOT NULL,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    PRIMARY KEY (id)
);

INSERT INTO _alembic_tmp_event_logs (id, source, object_type, object_id, action, summary, created_at, updated_at) SELECT event_logs.id, event_logs.source, event_logs.object_type, event_logs.object_id, event_logs.action, event_logs.summary, event_logs.created_at, event_logs.updated_at
FROM event_logs;

DROP TABLE event_logs;

ALTER TABLE _alembic_tmp_event_logs RENAME TO event_logs;

CREATE TABLE study_notes (
    id VARCHAR(36) NOT NULL,
    study_session_id VARCHAR(36) NOT NULL,
    lesson_id VARCHAR(36) NOT NULL,
    text TEXT DEFAULT '' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_study_note_lesson UNIQUE (study_session_id, lesson_id),
    FOREIGN KEY(study_session_id) REFERENCES course_study_sessions (id)
);

CREATE INDEX ix_study_notes_study_session_id ON study_notes (study_session_id);

CREATE TABLE study_note_receipts (
    id VARCHAR(36) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    study_session_id VARCHAR(36) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    result_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (idempotency_key),
    FOREIGN KEY(study_session_id) REFERENCES course_study_sessions (id)
);

CREATE INDEX ix_study_note_receipts_study_session_id ON study_note_receipts (study_session_id);
