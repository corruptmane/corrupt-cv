package main

import (
	"net/http"
	"testing"
	"time"

	"github.com/corruptmane/corrupt-cv/services/gateway/internal/config"
)

// Both servers must share the exact timeout posture: fast header
// reads, bounded idle keep-alives, and no write deadline — the SSE
// stream relies on unbounded writes.
func TestServerTimeouts(t *testing.T) {
	cfg := config.Config{AppAddr: ":8080", OpsAddr: ":9090"}
	appSrv, opsSrv := newServers(cfg, http.NewServeMux(), http.NewServeMux())

	servers := map[string]*http.Server{"app": appSrv, "ops": opsSrv}
	for name, srv := range servers {
		if srv.ReadHeaderTimeout != 10*time.Second {
			t.Errorf("%s ReadHeaderTimeout = %v, want 10s", name, srv.ReadHeaderTimeout)
		}
		if srv.IdleTimeout != 120*time.Second {
			t.Errorf("%s IdleTimeout = %v, want 2m", name, srv.IdleTimeout)
		}
		if srv.WriteTimeout != 0 {
			t.Errorf("%s WriteTimeout = %v, want 0 (SSE must not carry a write deadline)", name, srv.WriteTimeout)
		}
	}
}
