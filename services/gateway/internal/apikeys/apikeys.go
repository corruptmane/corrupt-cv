// Package apikeys hands provider API keys to the ai-processor
// out-of-band via Valkey. Keys are never published to NATS, persisted
// to Postgres, or logged; the processor claims them atomically with
// GETDEL and the TTL bounds their lifetime.
package apikeys

import (
	"context"
	"fmt"

	valkey "github.com/valkey-io/valkey-go"
)

// TTLSeconds bounds how long an unclaimed key survives.
const TTLSeconds = 900

// Store writes per-job API keys into Valkey.
type Store struct {
	client valkey.Client
}

// New wraps a Valkey client.
func New(client valkey.Client) *Store {
	return &Store{client: client}
}

func key(jobID string) string {
	return "cv:apikey:" + jobID
}

// Put stores the API key for a job under cv:apikey:{job_id} with a
// 900-second expiry. It must be called BEFORE publishing the
// JobRequested event so the processor never races an absent key.
func (s *Store) Put(ctx context.Context, jobID, apiKey string) error {
	cmd := s.client.B().Set().Key(key(jobID)).Value(apiKey).ExSeconds(TTLSeconds).Build()
	if err := s.client.Do(ctx, cmd).Error(); err != nil {
		return fmt.Errorf("store api key for job %s: %w", jobID, err)
	}
	return nil
}
