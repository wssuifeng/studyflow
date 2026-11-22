CREATE TABLE course_revisions (
    id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    number INTEGER NOT NULL,
    package_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(160),
    request_hash VARCHAR(64),
    result_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_course_revision_number UNIQUE (course_id, number),
    FOREIGN KEY(course_id) REFERENCES courses (id),
    UNIQUE (idempotency_key)
);

CREATE INDEX ix_course_revisions_course_id ON course_revisions (course_id);

ALTER TABLE lessons ADD COLUMN semantic_id VARCHAR(120) DEFAULT '' NOT NULL;

ALTER TABLE lessons ADD COLUMN included BOOLEAN DEFAULT 1 NOT NULL;

ALTER TABLE exercises ADD COLUMN semantic_id VARCHAR(120) DEFAULT '' NOT NULL;

ALTER TABLE exercises ADD COLUMN included BOOLEAN DEFAULT 1 NOT NULL;
