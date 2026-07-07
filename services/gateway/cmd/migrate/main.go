// Command migrate applies the database migrations and exits. Run as a one-shot
// step (a compose service / init job) before the gateway starts.
package main

import (
	"context"
	"log/slog"
	"os"

	"github.com/corruptmane/cv/services/gateway/internal/config"
	"github.com/corruptmane/cv/services/gateway/internal/store"
)

func main() {
	cfg := config.Load()
	if err := store.Migrate(context.Background(), cfg.PostgresDSN); err != nil {
		slog.Error("migration failed", "error", err)
		os.Exit(1)
	}
	slog.Info("migrations applied")
}
