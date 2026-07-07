// Package store owns the Postgres connection and exposes typed access to the
// generations table via sqlc-generated queries. Migrations are NOT run here;
// they run as a separate step (cmd/migrate) — see Migrate.
package store

import (
	"context"
	"database/sql"
	"embed"
	"encoding/json"

	"github.com/corruptmane/cv/services/gateway/internal/store/db"
	"github.com/exaring/otelpgx"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib" // registers the "pgx" database/sql driver
	"github.com/pressly/goose/v3"
)

//go:embed migrations/*.sql
var migrationsFS embed.FS

// Status values persisted in the generations table.
const (
	StatusQueued     = "queued"
	StatusStructured = "structured"
	StatusCompleted  = "completed"
	StatusFailed     = "failed"
)

type Store struct {
	pool *pgxpool.Pool
	q    *db.Queries
}

func New(ctx context.Context, dsn string) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, err
	}
	cfg.ConnConfig.Tracer = otelpgx.NewTracer() // OTel spans per query
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	return &Store{pool: pool, q: db.New(pool)}, nil
}

// Migrate applies the embedded goose migrations against dsn. Run as a one-shot
// step (cmd/migrate), not on gateway startup.
func Migrate(ctx context.Context, dsn string) error {
	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		return err
	}
	defer sqlDB.Close()
	goose.SetBaseFS(migrationsFS)
	if err := goose.SetDialect("postgres"); err != nil {
		return err
	}
	return goose.UpContext(ctx, sqlDB, "migrations")
}

func (s *Store) Ping(ctx context.Context) error { return s.pool.Ping(ctx) }
func (s *Store) Close()                         { s.pool.Close() }

// CreateParams is the input for a new generation row.
type CreateParams struct {
	ID             string
	Provider       string
	Model          string
	ExperienceText string
	JobDescription string
	Contacts       json.RawMessage
}

func (s *Store) Create(ctx context.Context, p CreateParams) (db.Generation, error) {
	return s.q.CreateGeneration(ctx, db.CreateGenerationParams{
		ID:             p.ID,
		Status:         StatusQueued,
		Provider:       p.Provider,
		Model:          p.Model,
		ExperienceText: p.ExperienceText,
		JobDescription: p.JobDescription,
		Contacts:       p.Contacts,
	})
}

func (s *Store) Get(ctx context.Context, id string) (db.Generation, error) {
	return s.q.GetGeneration(ctx, id)
}

func (s *Store) MarkStructured(ctx context.Context, id string, cvJSON json.RawMessage) error {
	return s.q.MarkStructured(ctx, db.MarkStructuredParams{ID: id, StructuredCv: cvJSON})
}

func (s *Store) MarkCompleted(ctx context.Context, id, objectKey string) error {
	return s.q.MarkCompleted(ctx, db.MarkCompletedParams{ID: id, PdfObjectKey: objectKey})
}

func (s *Store) MarkFailed(ctx context.Context, id, msg string) error {
	return s.q.MarkFailed(ctx, db.MarkFailedParams{ID: id, Error: msg})
}
