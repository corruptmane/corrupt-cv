-- +goose Up
CREATE TABLE profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id text NOT NULL UNIQUE,
    career_text text NOT NULL DEFAULT '',
    personal_info jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id text NOT NULL,
    profile_id uuid NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    job_description text NOT NULL,
    model_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'rendering', 'completed', 'failed')),
    error text,
    pdf_object_key text,
    cv jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX jobs_visitor_created_idx ON jobs (visitor_id, created_at DESC);
CREATE INDEX jobs_active_status_idx ON jobs (status) WHERE status NOT IN ('completed', 'failed');

-- +goose Down
DROP TABLE jobs;
DROP TABLE profiles;
