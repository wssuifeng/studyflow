ALTER TABLE submission_write_receipts ADD COLUMN payload_hash VARCHAR(64);

ALTER TABLE submission_write_receipts ADD COLUMN result_json TEXT;

CREATE TABLE submission_chain_links (
    parent_id VARCHAR(36) NOT NULL,
    child_id VARCHAR(36) NOT NULL,
    source VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (parent_id),
    FOREIGN KEY(parent_id) REFERENCES submissions (id),
    UNIQUE (child_id),
    FOREIGN KEY(child_id) REFERENCES submissions (id)
);
