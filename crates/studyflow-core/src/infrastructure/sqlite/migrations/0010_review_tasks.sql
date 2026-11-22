CREATE TABLE retest_tasks (
    id VARCHAR(36) NOT NULL,
    task_mode VARCHAR(20) DEFAULT 'general' NOT NULL,
    payload_json TEXT DEFAULT '{}' NOT NULL,
    parent_submission_id VARCHAR(36) NOT NULL,
    study_session_id VARCHAR(36),
    title VARCHAR(200) NOT NULL,
    prompt TEXT NOT NULL,
    requirements TEXT NOT NULL,
    objective TEXT NOT NULL,
    agent_reference TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (parent_submission_id),
    FOREIGN KEY(parent_submission_id) REFERENCES submissions (id),
    FOREIGN KEY(study_session_id) REFERENCES course_study_sessions (id),
    UNIQUE (idempotency_key)
);

ALTER TABLE submissions ADD COLUMN retest_task_id VARCHAR(36);

ALTER TABLE review_feedback ADD COLUMN issues_json TEXT DEFAULT '[]' NOT NULL;
