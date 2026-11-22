CREATE TABLE plan_course_items (
    id VARCHAR(36) NOT NULL,
    plan_line_id VARCHAR(36) NOT NULL,
    course_id VARCHAR(36) NOT NULL,
    sequence_number INTEGER DEFAULT '1' NOT NULL,
    status VARCHAR(24) DEFAULT 'PLANNED' NOT NULL,
    planned_start DATE,
    planned_end DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_plan_course_item_course UNIQUE (plan_line_id, course_id),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id),
    FOREIGN KEY(course_id) REFERENCES courses (id)
);

CREATE INDEX ix_plan_course_items_plan_line_id ON plan_course_items (plan_line_id);

CREATE INDEX ix_plan_course_items_course_id ON plan_course_items (course_id);

CREATE TABLE course_schedule_items (
    id VARCHAR(36) NOT NULL,
    plan_course_item_id VARCHAR(36) NOT NULL,
    scheduled_date DATE NOT NULL,
    position INTEGER DEFAULT '1' NOT NULL,
    start_time TIME,
    end_time TIME,
    status VARCHAR(24) DEFAULT 'PLANNED' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_course_schedule_day UNIQUE (plan_course_item_id, scheduled_date),
    FOREIGN KEY(plan_course_item_id) REFERENCES plan_course_items (id)
);

CREATE INDEX ix_course_schedule_items_plan_course_item_id ON course_schedule_items (plan_course_item_id);

CREATE INDEX ix_course_schedule_items_scheduled_date ON course_schedule_items (scheduled_date);

ALTER TABLE tasks ADD COLUMN course_schedule_item_id VARCHAR(36);

ALTER TABLE submissions ADD COLUMN parent_submission_id VARCHAR(36);

ALTER TABLE submissions ADD COLUMN attempt_number INTEGER DEFAULT '1' NOT NULL;

ALTER TABLE submissions ADD COLUMN attempt_kind VARCHAR(24) DEFAULT 'FIRST' NOT NULL;

ALTER TABLE submissions ADD COLUMN next_action TEXT DEFAULT '' NOT NULL;

ALTER TABLE review_feedback ADD COLUMN decision VARCHAR(32) DEFAULT 'PASSED' NOT NULL;

ALTER TABLE review_feedback ADD COLUMN next_action TEXT DEFAULT '' NOT NULL;

CREATE INDEX ix_tasks_course_schedule_item_id ON tasks (course_schedule_item_id);

CREATE INDEX ix_submissions_parent_submission_id ON submissions (parent_submission_id);
