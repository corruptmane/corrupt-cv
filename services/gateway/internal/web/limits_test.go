package web

import (
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func newLimitTestRouter(maxBody int64) *gin.Engine {
	gin.SetMode(gin.TestMode)
	s := &Server{log: slog.New(slog.NewTextHandler(io.Discard, nil)), maxBodyBytes: maxBody}
	r := gin.New()
	r.POST("/jobs", s.limitRequestBody(), func(c *gin.Context) {
		c.String(http.StatusOK, "ok")
	})
	return r
}

func doPOST(r *gin.Engine, body string, contentType string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/jobs", strings.NewReader(body))
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	return rec
}

// An urlencoded body past the configured cap must be rejected with 413
// before any handler logic runs.
func TestLimitRequestBodyOversized(t *testing.T) {
	r := newLimitTestRouter(1024)
	body := strings.Repeat("a", 2048)
	rec := doPOST(r, body, "application/x-www-form-urlencoded")
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want %d (body: %q)", rec.Code, http.StatusRequestEntityTooLarge, rec.Body.String())
	}
}

// A body within the cap passes through to the handler untouched.
func TestLimitRequestBodyWithinLimit(t *testing.T) {
	r := newLimitTestRouter(1024)
	rec := doPOST(r, "career_text=hello", "application/x-www-form-urlencoded")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d (body: %q)", rec.Code, http.StatusOK, rec.Body.String())
	}
}

// A malformed form body under the cap is a client error, not a 500 or
// a silently-empty form.
func TestLimitRequestBodyMalformedForm(t *testing.T) {
	r := newLimitTestRouter(1024)
	rec := doPOST(r, "not-a-multipart-body", "multipart/form-data; boundary=deadbeef")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d (body: %q)", rec.Code, http.StatusBadRequest, rec.Body.String())
	}
}

// validateJobSizes enforces the per-field character caps.
func TestValidateJobSizes(t *testing.T) {
	okDesc := strings.Repeat("d", MaxJobDescriptionChars)
	okCareer := strings.Repeat("c", MaxCareerTextChars)
	bigDesc := strings.Repeat("d", MaxJobDescriptionChars+1)
	bigCareer := strings.Repeat("c", MaxCareerTextChars+1)

	cases := []struct {
		name    string
		desc    string
		career  string
		wantErr error
	}{
		{"at caps", okDesc, okCareer, nil},
		{"empty", "", "", nil},
		{"description over cap", bigDesc, okCareer, ErrJobDescriptionTooLong},
		{"career text over cap", okDesc, bigCareer, ErrCareerTextTooLong},
		{"description checked first", bigDesc, bigCareer, ErrJobDescriptionTooLong},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateJobSizes(tc.desc, tc.career)
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("validateJobSizes() = %v, want %v", err, tc.wantErr)
			}
		})
	}
}
