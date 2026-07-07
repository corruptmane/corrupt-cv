package httpapi

import (
	"bytes"
	"strings"

	cvv1 "github.com/corruptmane/cv/gen/go/cv/v1"
)

func providerFromForm(v string) cvv1.Provider {
	switch strings.ToLower(v) {
	case "openai":
		return cvv1.Provider_PROVIDER_OPENAI
	case "anthropic":
		return cvv1.Provider_PROVIDER_ANTHROPIC
	case "gemini":
		return cvv1.Provider_PROVIDER_GEMINI
	case "ollama":
		return cvv1.Provider_PROVIDER_OLLAMA
	default:
		return cvv1.Provider_PROVIDER_TEST
	}
}

func providerName(p cvv1.Provider) string {
	switch p {
	case cvv1.Provider_PROVIDER_OPENAI:
		return "openai"
	case cvv1.Provider_PROVIDER_ANTHROPIC:
		return "anthropic"
	case cvv1.Provider_PROVIDER_GEMINI:
		return "gemini"
	case cvv1.Provider_PROVIDER_OLLAMA:
		return "ollama"
	default:
		return "test"
	}
}

// Display status keys consumed by the "status_fragment" template.
func statusKeyFromDB(status string) string {
	switch status {
	case "structured":
		return "rendering"
	case "completed":
		return "completed"
	case "failed":
		return "failed"
	default:
		return "queued"
	}
}

// statusKeyFromSubject maps the trailing token of cv.{jobID}.{type}.
func statusKeyFromSubject(subject string) string {
	switch subject[strings.LastIndex(subject, ".")+1:] {
	case "structured":
		return "rendering"
	case "completed":
		return "completed"
	case "failed":
		return "failed"
	default:
		return "queued"
	}
}

func terminal(key string) bool { return key == "completed" || key == "failed" }

func (s *Server) renderStatus(id, key, errMsg string) string {
	var buf bytes.Buffer
	_ = s.tmpl.ExecuteTemplate(&buf, "status_fragment", map[string]any{
		"ID":    id,
		"Key":   key,
		"Error": errMsg,
	})
	return buf.String()
}
