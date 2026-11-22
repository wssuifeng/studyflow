CREATE TABLE course_write_receipts (
    id VARCHAR(36) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    operation VARCHAR(40) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    result_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (idempotency_key),
    FOREIGN KEY(course_id) REFERENCES courses (id)
);

CREATE INDEX ix_course_write_receipts_course_id ON course_write_receipts (course_id);
