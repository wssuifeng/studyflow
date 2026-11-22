CREATE TABLE plan_lines (
    id VARCHAR(36) NOT NULL,
    name VARCHAR(120) NOT NULL,
    priority INTEGER DEFAULT '1' NOT NULL,
    status VARCHAR(24) DEFAULT 'ACTIVE' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (name)
);

CREATE TABLE stages (
    id VARCHAR(36) NOT NULL,
    plan_line_id VARCHAR(36) NOT NULL,
    name VARCHAR(160) NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    status VARCHAR(24) DEFAULT 'ACTIVE' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE TABLE tasks (
    id VARCHAR(36) NOT NULL,
    stage_id VARCHAR(36),
    title VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '' NOT NULL,
    scheduled_date DATE NOT NULL,
    status VARCHAR(24) DEFAULT 'TODO' NOT NULL,
    reason TEXT DEFAULT '' NOT NULL,
    next_action TEXT DEFAULT '' NOT NULL,
    priority INTEGER DEFAULT '1' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(stage_id) REFERENCES stages (id)
);

CREATE TABLE time_blocks (
    id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36) NOT NULL,
    block_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    actual_minutes INTEGER DEFAULT '0' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(task_id) REFERENCES tasks (id)
);

CREATE TABLE courses (
    id VARCHAR(36) NOT NULL,
    plan_line_id VARCHAR(36),
    title VARCHAR(200) NOT NULL,
    summary TEXT DEFAULT '' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    status VARCHAR(24) DEFAULT 'ACTIVE' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE TABLE lessons (
    id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    title VARCHAR(200) NOT NULL,
    position INTEGER DEFAULT '1' NOT NULL,
    markdown_path VARCHAR(500) NOT NULL,
    summary TEXT DEFAULT '' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(course_id) REFERENCES courses (id)
);

CREATE TABLE exercises (
    id VARCHAR(36) NOT NULL,
    lesson_id VARCHAR(36) NOT NULL,
    title VARCHAR(200) NOT NULL,
    prompt TEXT NOT NULL,
    requirements TEXT DEFAULT '' NOT NULL,
    position INTEGER DEFAULT '1' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(lesson_id) REFERENCES lessons (id)
);

CREATE TABLE submissions (
    id VARCHAR(36) NOT NULL,
    exercise_id VARCHAR(36) NOT NULL,
    task_id VARCHAR(36),
    answer_text TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'DRAFT' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    source VARCHAR(32) DEFAULT 'USER_WEB' NOT NULL,
    idempotency_key VARCHAR(160),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(exercise_id) REFERENCES exercises (id),
    FOREIGN KEY(task_id) REFERENCES tasks (id),
    UNIQUE (idempotency_key)
);

CREATE TABLE review_feedback (
    id VARCHAR(36) NOT NULL,
    submission_id VARCHAR(36) NOT NULL,
    summary TEXT NOT NULL,
    detail_markdown TEXT DEFAULT '' NOT NULL,
    issue_count INTEGER DEFAULT '0' NOT NULL,
    needs_revision BOOLEAN DEFAULT 0 NOT NULL,
    source VARCHAR(32) DEFAULT 'CODEX_CLI' NOT NULL,
    idempotency_key VARCHAR(160),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY(submission_id) REFERENCES submissions (id),
    UNIQUE (idempotency_key)
);

CREATE TABLE documents (
    id VARCHAR(36) NOT NULL,
    relative_path VARCHAR(500) NOT NULL,
    document_type VARCHAR(40) DEFAULT 'MARKDOWN' NOT NULL,
    status VARCHAR(24) DEFAULT 'PRESENT' NOT NULL,
    file_size INTEGER DEFAULT '0' NOT NULL,
    modified_at DATETIME,
    content_hash VARCHAR(64) DEFAULT '' NOT NULL,
    summary TEXT DEFAULT '' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (relative_path)
);

CREATE TABLE context_snapshots (
    id VARCHAR(36) NOT NULL,
    snapshot_date DATE NOT NULL,
    scope VARCHAR(32) DEFAULT 'today' NOT NULL,
    relative_path VARCHAR(500) NOT NULL,
    current_pointer TEXT DEFAULT '' NOT NULL,
    summary TEXT DEFAULT '' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE event_logs (
    id VARCHAR(36) NOT NULL,
    source VARCHAR(32) NOT NULL,
    object_type VARCHAR(40) NOT NULL,
    object_id VARCHAR(36) NOT NULL,
    action VARCHAR(80) NOT NULL,
    summary TEXT DEFAULT '' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_event_signature UNIQUE (source, object_type, object_id, action, summary)
);

CREATE INDEX ix_stages_plan_line_id ON stages (plan_line_id);

CREATE INDEX ix_tasks_stage_id ON tasks (stage_id);

CREATE INDEX ix_tasks_scheduled_date ON tasks (scheduled_date);

CREATE INDEX ix_tasks_status ON tasks (status);

CREATE INDEX ix_time_blocks_task_id ON time_blocks (task_id);

CREATE INDEX ix_courses_plan_line_id ON courses (plan_line_id);

CREATE INDEX ix_lessons_course_id ON lessons (course_id);

CREATE INDEX ix_exercises_lesson_id ON exercises (lesson_id);

CREATE INDEX ix_submissions_exercise_id ON submissions (exercise_id);

CREATE INDEX ix_submissions_task_id ON submissions (task_id);

CREATE INDEX ix_submissions_status ON submissions (status);

CREATE INDEX ix_review_feedback_submission_id ON review_feedback (submission_id);

CREATE INDEX ix_documents_status ON documents (status);

CREATE INDEX ix_context_snapshots_snapshot_date ON context_snapshots (snapshot_date);
