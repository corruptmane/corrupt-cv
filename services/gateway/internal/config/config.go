// Package config parses gateway configuration from environment
// variables (12-factor), with sensible localhost defaults for local
// development.
package config

import (
	"fmt"

	"github.com/caarlos0/env/v11"
)

// Config holds all gateway settings.
type Config struct {
	AppAddr string `env:"APP_ADDR" envDefault:":8080"`
	OpsAddr string `env:"OPS_ADDR" envDefault:":9090"`

	NATSURL     string `env:"NATS_URL" envDefault:"nats://localhost:4222"`
	DatabaseURL string `env:"DATABASE_URL" envDefault:"postgres://cv:cv@localhost:5432/cv?sslmode=disable"`
	ValkeyURL   string `env:"VALKEY_URL" envDefault:"valkey://localhost:6379"`

	// SessionSecret is the HMAC key (hex-ish string) for the visitor
	// cookie. The default is for local development only.
	SessionSecret string `env:"SESSION_SECRET" envDefault:"6c6f63616c2d6465762d6f6e6c792d736563726574"`

	ModelCatalogPath string `env:"MODEL_CATALOG_PATH" envDefault:"configs/model-catalog.yaml"`

	S3Endpoint     string `env:"S3_ENDPOINT" envDefault:"http://localhost:8081"`
	S3Region       string `env:"S3_REGION" envDefault:"us-east-1"`
	S3Bucket       string `env:"S3_BUCKET" envDefault:"cv"`
	S3AccessKeyID  string `env:"S3_ACCESS_KEY_ID" envDefault:"test:tester"`
	S3SecretKey    string `env:"S3_SECRET_ACCESS_KEY" envDefault:"testing"`
	S3UsePathStyle bool   `env:"S3_USE_PATH_STYLE" envDefault:"true"`

	LogLevel string `env:"LOG_LEVEL" envDefault:"INFO"`
}

// Load parses the environment into a Config.
func Load() (Config, error) {
	var cfg Config
	if err := env.Parse(&cfg); err != nil {
		return Config{}, fmt.Errorf("parse env: %w", err)
	}
	return cfg, nil
}
