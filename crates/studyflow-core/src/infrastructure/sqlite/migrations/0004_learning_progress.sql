CREATE TABLE learning_progress (
    id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    lesson_id VARCHAR(36) NOT NULL,
    progress_percent INTEGER DEFAULT '0' NOT NULL,
    status VARCHAR(24) DEFAULT 'NOT_STARTED' NOT NULL,
    last_position VARCHAR(500) DEFAULT '' NOT NULL,
    source VARCHAR(32) DEFAULT 'USER_ENGINE' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(course_id) REFERENCES courses (id),
    FOREIGN KEY(lesson_id) REFERENCES lessons (id),
    CONSTRAINT uq_learning_progress_course_lesson UNIQUE (course_id, lesson_id)
);

CREATE INDEX ix_learning_progress_course_id ON learning_progress (course_id);

CREATE INDEX ix_learning_progress_lesson_id ON learning_progress (lesson_id);

CREATE INDEX ix_learning_progress_status ON learning_progress (status);

CREATE TABLE submission_write_receipts (
    id VARCHAR(36) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    operation VARCHAR(40) NOT NULL,
    submission_id VARCHAR(36) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (idempotency_key),
    FOREIGN KEY(submission_id) REFERENCES submissions (id)
);

CREATE INDEX ix_submission_write_receipts_submission_id ON submission_write_receipts (submission_id);
