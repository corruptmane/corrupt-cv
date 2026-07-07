// Package secrets stores BYO API keys transiently in Valkey, keyed by job id
// with a short TTL. The gateway only writes; the AI Processor consumes via
// GETDEL. The key never touches Postgres, the bus, or logs.
package secrets

import (
	"context"
	"time"

	"github.com/redis/go-redis/extra/redisotel/v9"
	"github.com/redis/go-redis/v9"
)

type Store struct{ rdb *redis.Client }

func New(url string) (*Store, error) {
	opt, err := redis.ParseURL(url)
	if err != nil {
		return nil, err
	}
	rdb := redis.NewClient(opt)
	if err := redisotel.InstrumentTracing(rdb); err != nil {
		return nil, err
	}
	if err := redisotel.InstrumentMetrics(rdb); err != nil {
		return nil, err
	}
	return &Store{rdb: rdb}, nil
}

func key(jobID string) string { return "apikey:" + jobID }

// Put stores the API key with the configured TTL. A no-op for empty keys
// (keyless providers such as Ollama / TestModel).
func (s *Store) Put(ctx context.Context, jobID, apiKey string, ttl time.Duration) error {
	if apiKey == "" {
		return nil
	}
	return s.rdb.Set(ctx, key(jobID), apiKey, ttl).Err()
}

func (s *Store) Ping(ctx context.Context) error { return s.rdb.Ping(ctx).Err() }

func (s *Store) Close() error { return s.rdb.Close() }
