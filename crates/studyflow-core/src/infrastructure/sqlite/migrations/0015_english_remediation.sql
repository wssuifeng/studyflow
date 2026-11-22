ALTER TABLE plan_course_items ADD COLUMN track VARCHAR(20) DEFAULT 'MAIN' NOT NULL;

CREATE TABLE english_remediation_courses (
    course_id VARCHAR(36) NOT NULL,
    plan_line_id VARCHAR(36) NOT NULL,
    objective_ids_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    provenance_hash VARCHAR(64) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (course_id),
    FOREIGN KEY(course_id) REFERENCES courses (id),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE INDEX ix_english_remediation_courses_plan_line_id ON english_remediation_courses (plan_line_id);

CREATE TABLE english_remediation_sources (
    id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    aggregate_id VARCHAR(36) NOT NULL,
    evidence_id VARCHAR(36) NOT NULL,
    source_version INTEGER NOT NULL,
    rule_hash VARCHAR(64) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_remediation_evidence UNIQUE (course_id, evidence_id),
    FOREIGN KEY(course_id) REFERENCES english_remediation_courses (course_id),
    FOREIGN KEY(aggregate_id) REFERENCES english_error_aggregates (id),
    FOREIGN KEY(evidence_id) REFERENCES english_error_evidence (id)
);

CREATE INDEX ix_english_remediation_sources_aggregate_id ON english_remediation_sources (aggregate_id);

CREATE INDEX ix_english_remediation_sources_course_id ON english_remediation_sources (course_id);
