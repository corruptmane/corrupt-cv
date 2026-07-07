// Package config loads gateway settings from the environment (see
// docs/CONVENTIONS.md for the canonical variable list).
package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPAddr       string
	OpsAddr        string
	ModelsPath     string
	NATSURL        string
	NATSStream     string
	PostgresDSN    string
	ValkeyURL      string
	S3Endpoint     string
	S3Region       string
	S3Bucket       string
	S3AccessKey    string
	S3SecretKey    string
	S3UsePathStyle bool
	SecretTTL      time.Duration
	ServiceName    string
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func Load() Config {
	ttl, _ := strconv.Atoi(env("SECRET_TTL_SECONDS", "300"))
	return Config{
		HTTPAddr:       env("GATEWAY_HTTP_ADDR", ":8080"),
		OpsAddr:        env("GATEWAY_OPS_ADDR", ":9090"),
		ModelsPath:     env("MODELS_CONFIG_PATH", "config/models.yaml"),
		NATSURL:        env("NATS_URL", "nats://127.0.0.1:4222"),
		NATSStream:     env("NATS_STREAM", "CV"),
		PostgresDSN:    env("POSTGRES_DSN", "postgres://cv:cv@127.0.0.1:5432/cv?sslmode=disable"),
		ValkeyURL:      env("VALKEY_URL", "redis://127.0.0.1:6379/0"),
		S3Endpoint:     env("S3_ENDPOINT", "http://127.0.0.1:4566"),
		S3Region:       env("S3_REGION", "us-east-1"),
		S3Bucket:       env("S3_BUCKET", "cv-pdfs"),
		S3AccessKey:    env("S3_ACCESS_KEY_ID", "test"),
		S3SecretKey:    env("S3_SECRET_ACCESS_KEY", "test"),
		S3UsePathStyle: env("S3_USE_PATH_STYLE", "true") == "true",
		SecretTTL:      time.Duration(ttl) * time.Second,
		ServiceName:    env("OTEL_SERVICE_NAME", "gateway"),
	}
}
