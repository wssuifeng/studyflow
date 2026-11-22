CREATE TABLE plan_notebooks (
    id VARCHAR(36) NOT NULL,
    plan_line_id VARCHAR(36) NOT NULL,
    blocks_json TEXT DEFAULT '[]' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (plan_line_id),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE TABLE plan_notebook_receipts (
    id VARCHAR(36) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    plan_line_id VARCHAR(36) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    result_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (idempotency_key),
    FOREIGN KEY(plan_line_id) REFERENCES plan_lines (id)
);

CREATE INDEX ix_plan_notebook_receipts_plan_line_id ON plan_notebook_receipts (plan_line_id);
