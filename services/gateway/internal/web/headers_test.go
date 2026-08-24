package web

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

const (
	hdrNosniff  = "X-Content-Type-Options"
	hdrReferrer = "Referrer-Policy"
	hdrCSP      = "Content-Security-Policy"
	hdrHSTS     = "Strict-Transport-Security"
	valHSTS     = "max-age=31536000; includeSubDomains"
	valReferrer = "strict-origin-when-cross-origin"
	valCSP      = "default-src 'self'"
	valNosniff  = "nosniff"
)

func newHeadersTestRouter(secure bool) *gin.Engine {
	gin.SetMode(gin.TestMode)
	s := &Server{log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	r := gin.New()
	r.Use(s.securityHeaders(secure))
	// HTMX routes: an active-search GET partial and a form POST.
	r.GET("/models/search", func(c *gin.Context) { c.String(http.StatusOK, "<tr></tr>") })
	r.POST("/jobs", func(c *gin.Context) { c.String(http.StatusSeeOther, "") })
	return r
}

func TestSecurityHeaders(t *testing.T) {
	cases := []struct {
		name    string
		secure  bool
		want    map[string]string
		wantAbs []string
	}{
		{
			name:   "insecure",
			secure: false,
			want: map[string]string{
				hdrNosniff:  valNosniff,
				hdrReferrer: valReferrer,
				hdrCSP:      valCSP,
			},
			wantAbs: []string{hdrHSTS},
		},
		{
			name:   "secure",
			secure: true,
			want: map[string]string{
				hdrNosniff:  valNosniff,
				hdrReferrer: valReferrer,
				hdrCSP:      valCSP,
				hdrHSTS:     valHSTS,
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := newHeadersTestRouter(tc.secure)
			for _, route := range []struct{ method, path string }{
				{"GET", "/models/search"},
				{"POST", "/jobs"},
			} {
				req := httptest.NewRequest(route.method, route.path, nil)
				rec := httptest.NewRecorder()
				r.ServeHTTP(rec, req)
				if rec.Code != http.StatusOK && rec.Code != http.StatusSeeOther {
					t.Fatalf("%s %s: status = %d", route.method, route.path, rec.Code)
				}
				for k, want := range tc.want {
					if got := rec.Header().Get(k); got != want {
						t.Errorf("%s %s: header %s = %q, want %q", route.method, route.path, k, got, want)
					}
				}
				for _, k := range tc.wantAbs {
					if got := rec.Header().Get(k); got != "" {
						t.Errorf("%s %s: header %s = %q, want absent", route.method, route.path, k, got)
					}
				}
			}
		})
	}
}

// Headers are set before the first write, so a streaming (SSE-style)
// response keeps them and still delivers every chunk.
func TestSecurityHeadersPreserveStreaming(t *testing.T) {
	r := newHeadersTestRouter(true)
	r.GET("/jobs/id/events", func(c *gin.Context) {
		c.Header("Content-Type", "text/event-stream")
		c.Status(http.StatusOK)
		_, _ = c.Writer.Write([]byte("event: one\n\n"))
		c.Writer.(http.Flusher).Flush()
		_, _ = c.Writer.Write([]byte("event: two\n\n"))
	})

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest("GET", "/jobs/id/events", nil))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	if got := rec.Body.String(); got != "event: one\n\nevent: two\n\n" {
		t.Fatalf("streamed body = %q, want both chunks", got)
	}
	if rec.Header().Get(hdrCSP) != valCSP || rec.Header().Get(hdrHSTS) != valHSTS {
		t.Fatal("security headers missing on streamed response")
	}
}
