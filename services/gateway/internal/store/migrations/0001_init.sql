-- +goose Up
-- All columns are NOT NULL with empty defaults so generated Go types stay
-- simple (no nullable wrappers). Empty string / '{}' denote "not yet set".
CREATE TABLE generations (
    id              text        PRIMARY KEY,
    status          text        NOT NULL,
    provider        text        NOT NULL,
    model           text        NOT NULL,
    experience_text text        NOT NULL,
    job_description text        NOT NULL,
    contacts        jsonb       NOT NULL,
    structured_cv   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    pdf_object_key  text        NOT NULL DEFAULT '',
    error           text        NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX generations_created_at_idx ON generations (created_at DESC);

-- +goose Down
DROP TABLE generations;
