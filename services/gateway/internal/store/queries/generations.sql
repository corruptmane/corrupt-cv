-- name: CreateGeneration :one
INSERT INTO generations (
    id, status, provider, model, experience_text, job_description, contacts
) VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: GetGeneration :one
SELECT * FROM generations WHERE id = $1;

-- name: MarkStructured :exec
UPDATE generations
SET status = 'structured', structured_cv = $2, updated_at = now()
WHERE id = $1;

-- name: MarkCompleted :exec
UPDATE generations
SET status = 'completed', pdf_object_key = $2, updated_at = now()
WHERE id = $1;

-- name: MarkFailed :exec
UPDATE generations
SET status = 'failed', error = $2, updated_at = now()
WHERE id = $1;
