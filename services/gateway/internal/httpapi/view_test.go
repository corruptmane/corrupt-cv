package httpapi

import (
	"html/template"
	"strings"
	"testing"

	"github.com/corruptmane/cv/services/gateway/web"
)

func newTestServer(t *testing.T) *Server {
	t.Helper()
	return &Server{tmpl: template.Must(template.ParseFS(web.FS, "templates/*.html"))}
}

func TestRenderStatusFragments(t *testing.T) {
	s := newTestServer(t)

	completed := s.renderStatus("job-1", "completed", "")
	if !strings.Contains(completed, "/generations/job-1/pdf") {
		t.Errorf("completed fragment missing download link: %q", completed)
	}
	if !strings.Contains(completed, "Download PDF") {
		t.Errorf("completed fragment missing button label: %q", completed)
	}

	failed := s.renderStatus("job-1", "failed", "provider boom")
	if !strings.Contains(failed, "provider boom") {
		t.Errorf("failed fragment missing error: %q", failed)
	}

	for _, key := range []string{"queued", "rendering"} {
		if got := s.renderStatus("job-1", key, ""); !strings.Contains(got, "spinner") {
			t.Errorf("%s fragment missing spinner: %q", key, got)
		}
	}
}

func TestProviderRoundTrip(t *testing.T) {
	for _, name := range []string{"openai", "anthropic", "gemini", "ollama", "test"} {
		if got := providerName(providerFromForm(name)); got != name {
			t.Errorf("provider %q round-trip got %q", name, got)
		}
	}
	if providerName(providerFromForm("unknown")) != "test" {
		t.Errorf("unknown provider should default to test")
	}
}

func TestStatusKeyFromSubject(t *testing.T) {
	cases := map[string]string{
		"cv.abc.requested":  "queued",
		"cv.abc.structured": "rendering",
		"cv.abc.completed":  "completed",
		"cv.abc.failed":     "failed",
	}
	for subj, want := range cases {
		if got := statusKeyFromSubject(subj); got != want {
			t.Errorf("subject %q: want %q got %q", subj, want, got)
		}
	}
}
