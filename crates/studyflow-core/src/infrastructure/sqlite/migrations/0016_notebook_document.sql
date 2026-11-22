ALTER TABLE plan_notebooks ADD COLUMN format_version INTEGER DEFAULT '1' NOT NULL;

ALTER TABLE plan_notebooks ADD COLUMN document_json TEXT DEFAULT '{"entries":[]}' NOT NULL;

CREATE TABLE plan_notebook_sources (
    notebook_id VARCHAR(36) NOT NULL,
    id VARCHAR(64) NOT NULL,
    data_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (notebook_id, id),
    FOREIGN KEY(notebook_id) REFERENCES plan_notebooks (id)
);
