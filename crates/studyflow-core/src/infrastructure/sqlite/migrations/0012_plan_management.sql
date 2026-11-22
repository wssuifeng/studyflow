CREATE TABLE plan_write_receipts (
    id VARCHAR(36) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    result_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (idempotency_key)
);

ALTER TABLE plan_lines ADD COLUMN version INTEGER DEFAULT '1' NOT NULL;

ALTER TABLE plan_lines ADD COLUMN focus_course_id VARCHAR(36);
