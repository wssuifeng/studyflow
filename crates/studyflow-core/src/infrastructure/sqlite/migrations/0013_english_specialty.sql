ALTER TABLE courses ADD COLUMN learning_mode VARCHAR(20) DEFAULT 'general' NOT NULL;

CREATE TABLE english_items (
    exercise_id VARCHAR(36) NOT NULL,
    spec_json TEXT NOT NULL,
    PRIMARY KEY (exercise_id),
    FOREIGN KEY(exercise_id) REFERENCES exercises (id)
);

CREATE TABLE english_study_states (
    study_session_id VARCHAR(36) NOT NULL,
    plan_line_id VARCHAR(36),
    position INTEGER DEFAULT '0' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    completed BOOLEAN DEFAULT '0' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (study_session_id),
    FOREIGN KEY(study_session_id) REFERENCES course_study_sessions (id),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE TABLE english_check_attempts (
    id VARCHAR(36) NOT NULL,
    study_session_id VARCHAR(36) NOT NULL,
    exercise_id VARCHAR(36) NOT NULL,
    submission_id VARCHAR(36) NOT NULL,
    retest_task_id VARCHAR(36),
    answer_text TEXT NOT NULL,
    answer_version INTEGER NOT NULL,
    rule_hash VARCHAR(64) NOT NULL,
    result_json TEXT NOT NULL,
    assisted BOOLEAN DEFAULT '0' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(study_session_id) REFERENCES course_study_sessions (id),
    FOREIGN KEY(exercise_id) REFERENCES exercises (id),
    FOREIGN KEY(submission_id) REFERENCES submissions (id),
    FOREIGN KEY(retest_task_id) REFERENCES retest_tasks (id)
);

CREATE INDEX ix_en_check_scope ON english_check_attempts (study_session_id, exercise_id, created_at, id);

CREATE TABLE english_submission_details (
    submission_id VARCHAR(36) NOT NULL,
    last_attempt_id VARCHAR(36),
    assisted BOOLEAN DEFAULT '0' NOT NULL,
    skipped BOOLEAN DEFAULT '0' NOT NULL,
    evaluation_mode VARCHAR(20) DEFAULT 'local_exact' NOT NULL,
    PRIMARY KEY (submission_id),
    FOREIGN KEY(submission_id) REFERENCES submissions (id),
    FOREIGN KEY(last_attempt_id) REFERENCES english_check_attempts (id)
);

CREATE TABLE mistake_notebooks (
    id VARCHAR(36) NOT NULL,
    scope_key VARCHAR(80) NOT NULL,
    plan_line_id VARCHAR(36),
    domain VARCHAR(20) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_mistake_scope UNIQUE (scope_key, domain),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE TABLE english_error_aggregates (
    id VARCHAR(36) NOT NULL,
    notebook_id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    exercise_key VARCHAR(200) NOT NULL,
    rule_hash VARCHAR(64) NOT NULL,
    objective_ids_json TEXT DEFAULT '[]' NOT NULL,
    failed_attempts INTEGER DEFAULT '0' NOT NULL,
    failed_rounds INTEGER DEFAULT '0' NOT NULL,
    latest_attempt_id VARCHAR(36),
    version INTEGER DEFAULT '1' NOT NULL,
    archived BOOLEAN DEFAULT '0' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_en_aggregate UNIQUE (notebook_id, course_id, exercise_key, rule_hash),
    FOREIGN KEY(notebook_id) REFERENCES mistake_notebooks (id),
    FOREIGN KEY(course_id) REFERENCES courses (id),
    FOREIGN KEY(latest_attempt_id) REFERENCES english_check_attempts (id)
);

CREATE INDEX ix_en_aggregate_scope ON english_error_aggregates (notebook_id, course_id, archived, id);

CREATE TABLE english_error_evidence (
    id VARCHAR(36) NOT NULL,
    aggregate_id VARCHAR(36) NOT NULL,
    attempt_id VARCHAR(36),
    feedback_id VARCHAR(36),
    round_key VARCHAR(80) NOT NULL,
    valid_error BOOLEAN DEFAULT '1' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(aggregate_id) REFERENCES english_error_aggregates (id),
    UNIQUE (attempt_id),
    FOREIGN KEY(attempt_id) REFERENCES english_check_attempts (id),
    UNIQUE (feedback_id),
    FOREIGN KEY(feedback_id) REFERENCES review_feedback (id)
);

CREATE INDEX ix_en_evidence_item ON english_error_evidence (aggregate_id, round_key, id);

CREATE TABLE english_review_items (
    id VARCHAR(36) NOT NULL,
    aggregate_id VARCHAR(36) NOT NULL,
    reason VARCHAR(40) NOT NULL,
    status VARCHAR(30) DEFAULT 'PENDING' NOT NULL,
    retest_task_id VARCHAR(36),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (aggregate_id),
    FOREIGN KEY(aggregate_id) REFERENCES english_error_aggregates (id),
    FOREIGN KEY(retest_task_id) REFERENCES retest_tasks (id)
);

CREATE TABLE general_mistake_entries (
    id VARCHAR(36) NOT NULL,
    notebook_id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    exercise_key VARCHAR(200) NOT NULL,
    rule_hash VARCHAR(64) NOT NULL,
    latest_feedback_id VARCHAR(36) NOT NULL,
    status VARCHAR(32) NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    archived BOOLEAN DEFAULT '0' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_general_mistake UNIQUE (notebook_id, course_id, exercise_key, rule_hash),
    FOREIGN KEY(notebook_id) REFERENCES mistake_notebooks (id),
    FOREIGN KEY(course_id) REFERENCES courses (id),
    FOREIGN KEY(latest_feedback_id) REFERENCES review_feedback (id)
);

CREATE INDEX ix_general_mistake_scope ON general_mistake_entries (notebook_id, course_id, archived, id);

CREATE TABLE general_mistake_occurrences (
    id VARCHAR(36) NOT NULL,
    entry_id VARCHAR(36) NOT NULL,
    feedback_id VARCHAR(36) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(entry_id) REFERENCES general_mistake_entries (id),
    UNIQUE (feedback_id),
    FOREIGN KEY(feedback_id) REFERENCES review_feedback (id)
);
