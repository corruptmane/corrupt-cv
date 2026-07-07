// Command gateway is the CV generator's HTTP front end and the single
// NATS JetStream authority: it provisions the stream, durable
// consumers and the model-catalog KV bucket before serving traffic.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/exaring/otelpgx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats.go"
	natsjs "github.com/nats-io/nats.go/jetstream"
	valkey "github.com/valkey-io/valkey-go"
	"github.com/valkey-io/valkey-go/valkeyotel"
	"go.opentelemetry.io/contrib/bridges/otelslog"

	"github.com/corruptmane/cv/services/gateway/internal/apikeys"
	"github.com/corruptmane/cv/services/gateway/internal/catalog"
	"github.com/corruptmane/cv/services/gateway/internal/config"
	"github.com/corruptmane/cv/services/gateway/internal/jetstream"
	"github.com/corruptmane/cv/services/gateway/internal/jobs"
	"github.com/corruptmane/cv/services/gateway/internal/ops"
	"github.com/corruptmane/cv/services/gateway/internal/s3"
	"github.com/corruptmane/cv/services/gateway/internal/store"
	"github.com/corruptmane/cv/services/gateway/internal/telemetry"
	"github.com/corruptmane/cv/services/gateway/internal/web"
)

func main() {
	if err := run(); err != nil {
		slog.Error("gateway exited with error", "error", err)
		os.Exit(1)
	}
}

// newLogger builds the process logger: JSON to stdout, and — when
// telemetry is enabled — a fanout that also feeds every record to the
// OTel log bridge (which attaches trace/span ids from the record ctx).
func newLogger(level string, otelEnabled bool) *slog.Logger {
	var lvl slog.Level
	switch strings.ToUpper(level) {
	case "DEBUG":
		lvl = slog.LevelDebug
	case "WARN", "WARNING":
		lvl = slog.LevelWarn
	case "ERROR":
		lvl = slog.LevelError
	default:
		lvl = slog.LevelInfo
	}
	var handler slog.Handler = slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: lvl})
	if otelEnabled {
		handler = telemetry.NewFanoutHandler(handler, otelslog.NewHandler(telemetry.ScopeName))
	}
	return slog.New(handler)
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	rootCtx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	// Telemetry first: providers must exist before the logger (OTel
	// bridge) and before any instrumented client is constructed. A
	// no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
	otelEnabled := telemetry.Enabled()
	otelShutdown, err := telemetry.Setup(rootCtx)
	if err != nil {
		return fmt.Errorf("setup telemetry: %w", err)
	}
	defer func() {
		flushCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := otelShutdown(flushCtx); err != nil {
			slog.Warn("telemetry shutdown", "error", err)
		}
	}()

	log := newLogger(cfg.LogLevel, otelEnabled)
	slog.SetDefault(log)

	bootCtx, bootCancel := context.WithTimeout(rootCtx, 30*time.Second)
	defer bootCancel()

	// Postgres.
	poolCfg, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("parse DATABASE_URL: %w", err)
	}
	if otelEnabled {
		poolCfg.ConnConfig.Tracer = otelpgx.NewTracer()
	}
	pool, err := pgxpool.NewWithConfig(bootCtx, poolCfg)
	if err != nil {
		return fmt.Errorf("create pgx pool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(bootCtx); err != nil {
		return fmt.Errorf("ping postgres: %w", err)
	}
	st := store.New(pool)

	// Valkey.
	valkeyOpt, err := valkey.ParseURL(cfg.ValkeyURL)
	if err != nil {
		return fmt.Errorf("parse VALKEY_URL: %w", err)
	}
	valkeyClient, err := valkey.NewClient(valkeyOpt)
	if err != nil {
		return fmt.Errorf("connect valkey: %w", err)
	}
	if otelEnabled {
		valkeyClient = valkeyotel.WithClient(valkeyClient)
	}
	defer valkeyClient.Close()
	keys := apikeys.New(valkeyClient)

	// NATS + JetStream.
	nc, err := nats.Connect(cfg.NATSURL,
		nats.Name("cv-gateway"),
		nats.MaxReconnects(-1),
	)
	if err != nil {
		return fmt.Errorf("connect nats: %w", err)
	}
	defer nc.Close()
	js, err := natsjs.New(nc)
	if err != nil {
		return fmt.Errorf("create jetstream context: %w", err)
	}

	// Provision stream, durable consumers and KV bucket, then seed the
	// model catalog — all BEFORE any listener starts.
	ready := &ops.Readiness{}
	kv, err := jetstream.Provision(bootCtx, js)
	if err != nil {
		return fmt.Errorf("provision jetstream: %w", err)
	}
	cat, err := catalog.Load(cfg.ModelCatalogPath)
	if err != nil {
		return err
	}
	if err := cat.Seed(bootCtx, kv); err != nil {
		return fmt.Errorf("seed model catalog: %w", err)
	}
	ready.SetProvisioned()
	log.Info("jetstream provisioned",
		"stream", jetstream.StreamName,
		"kv_bucket", jetstream.CatalogBucket,
		"catalog_entries", len(cat.All()),
	)

	// Background projection: events consumer, advisory watcher, sweeper.
	runner := jobs.NewRunner(js, st, log)
	if err := runner.Start(rootCtx); err != nil {
		return fmt.Errorf("start jobs runner: %w", err)
	}
	defer runner.Stop()

	// HTTP servers.
	objects := s3.New(s3.Config{
		Endpoint:     cfg.S3Endpoint,
		Region:       cfg.S3Region,
		Bucket:       cfg.S3Bucket,
		AccessKeyID:  cfg.S3AccessKeyID,
		SecretKey:    cfg.S3SecretKey,
		UsePathStyle: cfg.S3UsePathStyle,
	})
	gin.SetMode(gin.ReleaseMode)
	webServer := web.New(st, cat, js, jetstream.NewPublisher(js), keys, objects, log)

	appSrv := &http.Server{
		Addr:              cfg.AppAddr,
		Handler:           webServer.Router([]byte(cfg.SessionSecret), otelEnabled),
		ReadHeaderTimeout: 10 * time.Second,
	}
	opsSrv := &http.Server{
		Addr:              cfg.OpsAddr,
		Handler:           ops.Handler(pool, nc, ready),
		ReadHeaderTimeout: 10 * time.Second,
	}

	errCh := make(chan error, 2)
	go func() {
		log.Info("app server listening", "addr", cfg.AppAddr)
		if err := appSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("app server: %w", err)
		}
	}()
	go func() {
		log.Info("ops server listening", "addr", cfg.OpsAddr)
		if err := opsSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("ops server: %w", err)
		}
	}()

	select {
	case err := <-errCh:
		return err
	case <-rootCtx.Done():
	}

	// Graceful shutdown: stop accepting, let in-flight requests (and
	// SSE streams) finish, drain consumers, close pools (deferred).
	log.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := appSrv.Shutdown(shutdownCtx); err != nil {
		log.Warn("app server shutdown", "error", err)
	}
	if err := opsSrv.Shutdown(shutdownCtx); err != nil {
		log.Warn("ops server shutdown", "error", err)
	}
	runner.Stop()
	if err := nc.Drain(); err != nil {
		log.Warn("nats drain", "error", err)
	}
	log.Info("shutdown complete")
	return nil
}
