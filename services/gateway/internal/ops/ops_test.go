package ops

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
)

type stubNatsChecker struct{ status nats.Status }

func (s stubNatsChecker) Status() nats.Status { return s.status }

type fakePinger struct {
	err   error
	delay time.Duration
}

func (f fakePinger) Ping(ctx context.Context) error {
	if f.delay > 0 {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(f.delay):
		}
	}
	return f.err
}

type fakeBucketProber struct {
	err error
}

func (f fakeBucketProber) HeadBucket(context.Context) error { return f.err }

func newTestHandler(valkey Pinger, objects BucketProber) http.Handler {
	return Handler(
		fakePinger{},
		stubNatsChecker{nats.CONNECTED},
		func() *Readiness { r := &Readiness{}; r.SetProvisioned(); return r }(),
		valkey,
		objects,
	)
}

func getReadyz(h http.Handler) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestReadyzHealthy(t *testing.T) {
	rec := getReadyz(newTestHandler(fakePinger{}, fakeBucketProber{}))
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %q)", rec.Code, rec.Body.String())
	}
}

func TestReadyzValkeyDown(t *testing.T) {
	rec := getReadyz(newTestHandler(fakePinger{err: errors.New("conn refused")}, fakeBucketProber{}))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	if body := rec.Body.String(); !contains(body, "valkey") {
		t.Fatalf("body %q must name valkey as the degraded dependency", body)
	}
}

func TestReadyzObjectStorageDown(t *testing.T) {
	rec := getReadyz(newTestHandler(fakePinger{}, fakeBucketProber{err: errors.New("no route")}))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	if body := rec.Body.String(); !contains(body, "object storage") {
		t.Fatalf("body %q must name object storage as the degraded dependency", body)
	}
}

// A probe hanging past its per-dependency timeout must degrade the
// endpoint instead of blocking the kubelet.
func TestReadyzProbeTimeout(t *testing.T) {
	saved := probeTimeout
	probeTimeout = 50 * time.Millisecond
	t.Cleanup(func() { probeTimeout = saved })

	rec := getReadyz(newTestHandler(fakePinger{delay: 2 * time.Second}, fakeBucketProber{}))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 on hung probe", rec.Code)
	}
}

func contains(s, substr string) bool {
	return strings.Contains(s, substr)
}
