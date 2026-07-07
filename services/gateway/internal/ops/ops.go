// Package ops serves the operational endpoints on a separate listener
// (plain net/http, no gin): /healthz for liveness and /readyz for
// readiness.
package ops

import (
	"context"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats.go"
)

// Readiness tracks whether boot-time provisioning has finished.
type Readiness struct {
	provisioned atomic.Bool
}

// SetProvisioned marks JetStream provisioning as complete.
func (r *Readiness) SetProvisioned() {
	r.provisioned.Store(true)
}

// Provisioned reports whether provisioning has completed.
func (r *Readiness) Provisioned() bool {
	return r.provisioned.Load()
}

// Handler returns the ops mux. /healthz is always 200; /readyz is 200
// only when Postgres pings, the NATS connection is up, and JetStream
// provisioning has completed.
func Handler(pool *pgxpool.Pool, nc *nats.Conn, ready *Readiness) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()

		if !ready.Provisioned() {
			http.Error(w, "provisioning incomplete", http.StatusServiceUnavailable)
			return
		}
		if nc.Status() != nats.CONNECTED {
			http.Error(w, "nats not connected", http.StatusServiceUnavailable)
			return
		}
		if err := pool.Ping(ctx); err != nil {
			http.Error(w, "postgres unreachable", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready"))
	})

	return mux
}
