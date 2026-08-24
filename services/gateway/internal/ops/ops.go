// Package ops serves the operational endpoints on a separate listener
// (plain net/http, no gin): /healthz for liveness and /readyz for
// readiness.
package ops

import (
	"context"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/valkey-io/valkey-go"
)

// probeTimeout bounds each dependency probe individually so one hung
// backend cannot stall the kubelet's readiness check.
var probeTimeout = 500 * time.Millisecond

// Pinger is a cheap liveness round trip against a datastore.
type Pinger interface {
	Ping(ctx context.Context) error
}

// BucketProber verifies object-storage access.
type BucketProber interface {
	HeadBucket(ctx context.Context) error
}

// postgresPinger is the subset of *pgxpool.Pool readiness needs.
type postgresPinger interface {
	Ping(ctx context.Context) error
}

// natsChecker is the subset of *nats.Conn readiness needs.
type natsChecker interface {
	Status() nats.Status
}

// ValkeyPinger adapts a valkey client to Pinger via a PING command.
type ValkeyPinger struct {
	Client valkey.Client
}

// Ping issues a round-trip PING against Valkey.
func (p ValkeyPinger) Ping(ctx context.Context) error {
	return p.Client.Do(ctx, p.Client.B().Ping().Build()).Error()
}

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
// only when JetStream provisioning has completed, NATS is connected,
// Postgres, Valkey, and object storage all answer within their probe
// timeout. The first degraded dependency wins and is named in the 503.
func Handler(postgres postgresPinger, nc natsChecker, ready *Readiness, valkeyClient Pinger, objects BucketProber) http.Handler {
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
		if err := probe(ctx, postgres.Ping); err != nil {
			http.Error(w, "postgres unreachable", http.StatusServiceUnavailable)
			return
		}
		if err := probe(ctx, valkeyClient.Ping); err != nil {
			http.Error(w, "valkey unreachable", http.StatusServiceUnavailable)
			return
		}
		if err := probe(ctx, objects.HeadBucket); err != nil {
			http.Error(w, "object storage unreachable", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready"))
	})

	return mux
}

// probe runs one dependency check under the per-probe timeout.
func probe(ctx context.Context, check func(context.Context) error) error {
	probeCtx, cancel := context.WithTimeout(ctx, probeTimeout)
	defer cancel()
	return check(probeCtx)
}
