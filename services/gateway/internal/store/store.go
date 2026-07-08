// Package store wraps all Postgres access for the gateway.
//
// Job status transitions are guarded in SQL so that concurrent event
// deliveries can never resurrect a terminal job:
//
//	structured: pending -> rendering (+ cv jsonb)
//	rendered:   any non-terminal -> completed (+ pdf_object_key)
//	failed:     any non-terminal -> failed (+ error)
package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ErrNotFound is returned when a row does not exist (or is not visible
// to the requesting visitor).
var ErrNotFound = errors.New("store: not found")

// Profile is a visitor's saved career profile.
type Profile struct {
	ID           string
	VisitorID    string
	CareerText   string
	PersonalInfo []byte // protojson-encoded cvgen.cv.v1.PersonalInfo, nil when unset
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

// Job is one CV generation job.
type Job struct {
	ID             string
	VisitorID      string
	ProfileID      string
	JobDescription string
	ModelKey       string
	Status         string
	Error          *string
	PDFObjectKey   *string
	CreatedAt      time.Time
	UpdatedAt      time.Time
}

// Store executes queries against the gateway database.
type Store struct {
	pool *pgxpool.Pool
}

// New wraps a pgx pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// UpsertProfile creates or updates the visitor's profile.
// personalInfoJSON must be protojson-encoded cvgen.cv.v1.PersonalInfo.
func (s *Store) UpsertProfile(ctx context.Context, visitorID, careerText string, personalInfoJSON []byte) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO profiles (visitor_id, career_text, personal_info)
		VALUES ($1, $2, $3)
		ON CONFLICT (visitor_id) DO UPDATE
		SET career_text = EXCLUDED.career_text,
		    personal_info = EXCLUDED.personal_info,
		    updated_at = now()`,
		visitorID, careerText, personalInfoJSON)
	if err != nil {
		return fmt.Errorf("upsert profile: %w", err)
	}
	return nil
}

// GetProfile returns the visitor's profile, or ErrNotFound.
func (s *Store) GetProfile(ctx context.Context, visitorID string) (*Profile, error) {
	var p Profile
	err := s.pool.QueryRow(ctx, `
		SELECT id, visitor_id, career_text, personal_info, created_at, updated_at
		FROM profiles WHERE visitor_id = $1`,
		visitorID).Scan(&p.ID, &p.VisitorID, &p.CareerText, &p.PersonalInfo, &p.CreatedAt, &p.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get profile: %w", err)
	}
	return &p, nil
}

// CreateJob inserts a pending job and returns its id.
func (s *Store) CreateJob(ctx context.Context, visitorID, profileID, jobDescription, modelKey string) (string, error) {
	var id string
	err := s.pool.QueryRow(ctx, `
		INSERT INTO jobs (visitor_id, profile_id, job_description, model_key, status)
		VALUES ($1, $2, $3, $4, 'pending')
		RETURNING id`,
		visitorID, profileID, jobDescription, modelKey).Scan(&id)
	if err != nil {
		return "", fmt.Errorf("create job: %w", err)
	}
	return id, nil
}

const jobColumns = `id, visitor_id, profile_id, job_description, model_key, status, error, pdf_object_key, created_at, updated_at`

func scanJob(row pgx.Row) (*Job, error) {
	var j Job
	err := row.Scan(&j.ID, &j.VisitorID, &j.ProfileID, &j.JobDescription, &j.ModelKey,
		&j.Status, &j.Error, &j.PDFObjectKey, &j.CreatedAt, &j.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("scan job: %w", err)
	}
	return &j, nil
}

// GetJob returns the job only when it belongs to the visitor.
func (s *Store) GetJob(ctx context.Context, id, visitorID string) (*Job, error) {
	return scanJob(s.pool.QueryRow(ctx,
		`SELECT `+jobColumns+` FROM jobs WHERE id = $1 AND visitor_id = $2`, id, visitorID))
}

// ListJobs returns the visitor's most recent jobs, newest first.
func (s *Store) ListJobs(ctx context.Context, visitorID string, limit int) ([]Job, error) {
	if limit <= 0 {
		limit = 20
	}
	rows, err := s.pool.Query(ctx,
		`SELECT `+jobColumns+` FROM jobs
		 WHERE visitor_id = $1 ORDER BY created_at DESC LIMIT $2`,
		visitorID, limit)
	if err != nil {
		return nil, fmt.Errorf("list jobs: %w", err)
	}
	defer rows.Close()

	var jobs []Job
	for rows.Next() {
		j, err := scanJob(rows)
		if err != nil {
			return nil, err
		}
		jobs = append(jobs, *j)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("list jobs: %w", err)
	}
	return jobs, nil
}

// MarkRendering moves a pending job to rendering and persists the
// structured CV (protojson of cvgen.cv.v1.CV). No-op for any other
// current status.
func (s *Store) MarkRendering(ctx context.Context, id string, cvJSON []byte) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE jobs SET status = 'rendering', cv = $2, updated_at = now()
		WHERE id = $1 AND status = 'pending'`,
		id, cvJSON)
	if err != nil {
		return fmt.Errorf("mark rendering: %w", err)
	}
	return nil
}

// MarkCompleted moves a non-terminal job to completed with its PDF
// key. When the transition applies it returns the job's created_at
// and true; when the job is missing or already terminal it returns
// false (redeliveries make that a normal case, not an error).
func (s *Store) MarkCompleted(ctx context.Context, id, pdfObjectKey string) (time.Time, bool, error) {
	var createdAt time.Time
	err := s.pool.QueryRow(ctx, `
		UPDATE jobs SET status = 'completed', pdf_object_key = $2, updated_at = now()
		WHERE id = $1 AND status NOT IN ('completed', 'failed')
		RETURNING created_at`,
		id, pdfObjectKey).Scan(&createdAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return time.Time{}, false, nil
	}
	if err != nil {
		return time.Time{}, false, fmt.Errorf("mark completed: %w", err)
	}
	return createdAt, true, nil
}

// MarkFailed moves a non-terminal job to failed with an error message.
// Return values follow MarkCompleted.
func (s *Store) MarkFailed(ctx context.Context, id, errText string) (time.Time, bool, error) {
	var createdAt time.Time
	err := s.pool.QueryRow(ctx, `
		UPDATE jobs SET status = 'failed', error = $2, updated_at = now()
		WHERE id = $1 AND status NOT IN ('completed', 'failed')
		RETURNING created_at`,
		id, errText).Scan(&createdAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return time.Time{}, false, nil
	}
	if err != nil {
		return time.Time{}, false, fmt.Errorf("mark failed: %w", err)
	}
	return createdAt, true, nil
}

// SweepStuck fails every non-terminal job that has not progressed for
// olderThan, returning the number of jobs swept.
func (s *Store) SweepStuck(ctx context.Context, olderThan time.Duration) (int64, error) {
	tag, err := s.pool.Exec(ctx, `
		UPDATE jobs SET status = 'failed', error = 'job timed out', updated_at = now()
		WHERE status NOT IN ('completed', 'failed')
		  AND updated_at < now() - make_interval(secs => $1)`,
		olderThan.Seconds())
	if err != nil {
		return 0, fmt.Errorf("sweep stuck: %w", err)
	}
	return tag.RowsAffected(), nil
}
