// Command gateway is the HTMX/Gin entrypoint: serves the UI, publishes
// generation requests, and projects result events into Postgres.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	cvv1 "github.com/corruptmane/cv/gen/go/cv/v1"
	"github.com/corruptmane/cv/services/gateway/internal/bus"
	"github.com/corruptmane/cv/services/gateway/internal/config"
	"github.com/corruptmane/cv/services/gateway/internal/httpapi"
	"github.com/corruptmane/cv/services/gateway/internal/modelcfg"
	"github.com/corruptmane/cv/services/gateway/internal/secrets"
	"github.com/corruptmane/cv/services/gateway/internal/storage"
	"github.com/corruptmane/cv/services/gateway/internal/store"
	"github.com/corruptmane/cv/services/gateway/internal/telemetry"
	"github.com/nats-io/nats.go/jetstream"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func main() {
	if err := run(); err != nil {
		slog.Error("gateway exited", "error", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	cfg := config.Load()

	shutdownTel, metricsHandler, err := telemetry.Setup(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = shutdownTel(context.Background()) }()

	models, err := modelcfg.Load(cfg.ModelsPath)
	if err != nil {
		return err
	}

	st, err := store.New(ctx, cfg.PostgresDSN)
	if err != nil {
		return err
	}
	defer st.Close()

	sec, err := secrets.New(cfg.ValkeyURL)
	if err != nil {
		return err
	}
	defer sec.Close()

	stor := storage.New(storage.Config{
		Endpoint:     cfg.S3Endpoint,
		Region:       cfg.S3Region,
		Bucket:       cfg.S3Bucket,
		AccessKey:    cfg.S3AccessKey,
		SecretKey:    cfg.S3SecretKey,
		UsePathStyle: cfg.S3UsePathStyle,
	})

	b, err := bus.Connect(ctx, cfg.NATSURL, cfg.NATSStream)
	if err != nil {
		return err
	}
	defer b.Close()

	cc, err := b.ConsumePersist(ctx, persistHandler(st))
	if err != nil {
		return err
	}
	defer cc.Stop()

	srv := httpapi.New(httpapi.Deps{
		Store: st, Secrets: sec, Storage: stor, Bus: b, Models: models, Cfg: cfg,
	})
	appServer := &http.Server{Addr: cfg.HTTPAddr, Handler: srv.Engine()}

	ready := func() bool {
		rctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		return b.Connected() && st.Ping(rctx) == nil && sec.Ping(rctx) == nil
	}
	opsServer := &http.Server{Addr: cfg.OpsAddr, Handler: opsMux(metricsHandler, ready)}

	go serve(appServer, "app", stop)
	go serve(opsServer, "ops", stop)
	slog.Info("gateway listening", "app", cfg.HTTPAddr, "ops", cfg.OpsAddr)

	<-ctx.Done()
	slog.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = opsServer.Shutdown(shutdownCtx)
	return appServer.Shutdown(shutdownCtx)
}

func serve(s *http.Server, name string, stop context.CancelFunc) {
	if err := s.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("server error", "server", name, "error", err)
		stop()
	}
}

// opsMux serves the operational endpoints: liveness, readiness, and Prometheus
// metrics (scraped by VictoriaMetrics).
func opsMux(metrics http.Handler, ready func() bool) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/livez", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("content-type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("content-type", "application/json")
		if !ready() {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(`{"status":"not ready"}`))
			return
		}
		_, _ = w.Write([]byte(`{"status":"ready"}`))
	})
	mux.Handle("/metrics", metrics)
	return mux
}

// persistHandler projects result events (structured/completed/failed) onto the
// generations table. The gateway is the sole Postgres writer. Each message is
// handled in a CONSUMER span continuing the producer's trace, so the otelpgx
// query spans nest underneath it.
func persistHandler(st *store.Store) jetstream.MessageHandler {
	tracer := otel.Tracer("gateway.persist")
	return func(msg jetstream.Msg) {
		ctx := telemetry.ExtractNATS(context.Background(), msg.Headers())
		ctx, span := tracer.Start(ctx, "persist "+msg.Subject(), trace.WithSpanKind(trace.SpanKindConsumer))
		defer span.End()

		switch msg.Subject()[strings.LastIndex(msg.Subject(), ".")+1:] {
		case "structured":
			var ev cvv1.CVStructured
			if err := proto.Unmarshal(msg.Data(), &ev); err != nil {
				_ = msg.Term()
				return
			}
			cvJSON, _ := protojson.Marshal(ev.Cv)
			if err := st.MarkStructured(ctx, ev.JobId, cvJSON); err != nil {
				slog.ErrorContext(ctx, "mark structured", "error", err, "job_id", ev.JobId)
				_ = msg.Nak()
				return
			}
		case "completed":
			var ev cvv1.CVCompleted
			if err := proto.Unmarshal(msg.Data(), &ev); err != nil {
				_ = msg.Term()
				return
			}
			if err := st.MarkCompleted(ctx, ev.JobId, ev.ObjectKey); err != nil {
				slog.ErrorContext(ctx, "mark completed", "error", err, "job_id", ev.JobId)
				_ = msg.Nak()
				return
			}
		case "failed":
			var ev cvv1.CVFailed
			if err := proto.Unmarshal(msg.Data(), &ev); err != nil {
				_ = msg.Term()
				return
			}
			if err := st.MarkFailed(ctx, ev.JobId, ev.Message); err != nil {
				slog.ErrorContext(ctx, "mark failed", "error", err, "job_id", ev.JobId)
				_ = msg.Nak()
				return
			}
		}
		_ = msg.Ack()
	}
}
