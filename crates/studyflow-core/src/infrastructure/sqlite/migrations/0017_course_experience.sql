ALTER TABLE course_study_sessions ADD COLUMN hint_tracking_enabled BOOLEAN DEFAULT '0' NOT NULL;

ALTER TABLE plan_course_items ADD COLUMN management_position VARCHAR(20) DEFAULT 'NORMAL' NOT NULL;

ALTER TABLE plan_course_items ADD COLUMN management_reason TEXT DEFAULT '' NOT NULL;

ALTER TABLE review_feedback ADD COLUMN reference_hash VARCHAR(64);

ALTER TABLE review_feedback ADD COLUMN reference_revision INTEGER;

ALTER TABLE review_feedback ADD COLUMN reference_reason TEXT DEFAULT '' NOT NULL;

CREATE TABLE course_reference_views (
    study_session_id VARCHAR(36) NOT NULL,
    exercise_id VARCHAR(36) NOT NULL,
    reference_hash VARCHAR(64) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (study_session_id, exercise_id, reference_hash),
    FOREIGN KEY(study_session_id) REFERENCES course_study_sessions (id),
    FOREIGN KEY(exercise_id) REFERENCES exercises (id)
);
