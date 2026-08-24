package web

import (
	"errors"
	"fmt"
	"mime"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// Character caps for the free-text job fields. The body cap bounds the
// wire; these bound what reaches the pipeline and the LLM prompt.
const (
	MaxCareerTextChars     = 100_000
	MaxJobDescriptionChars = 20_000
)

// ErrJobDescriptionTooLong and ErrCareerTextTooLong mark the field-cap
// rejections surfaced by validateJobSizes.
var (
	ErrJobDescriptionTooLong = errors.New("job description too long")
	ErrCareerTextTooLong     = errors.New("career history too long")
)

// formMemLimit bounds how much of a multipart body is buffered in RAM;
// the hard size cap itself comes from MaxBytesReader.
const formMemLimit = 1 << 20

// limitRequestBody caps the POST body at the configured size and parses
// the form eagerly, so an oversized body fails here with a deterministic
// 413 instead of surfacing later as silently-empty form fields.
func (s *Server) limitRequestBody() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, s.maxBodyBytes)
		if err := parseForm(c.Request); err != nil {
			var maxErr *http.MaxBytesError
			if errors.As(err, &maxErr) {
				c.String(http.StatusRequestEntityTooLarge, "request body too large")
			} else {
				c.String(http.StatusBadRequest, "malformed form body")
			}
			c.Abort()
			return
		}
		c.Next()
	}
}

// parseForm eagerly consumes the request body: multipart bodies through
// ParseMultipartForm, everything else through ParseForm (which handles
// application/x-www-form-urlencoded and ignores unreadable body types).
func parseForm(r *http.Request) error {
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err == nil && strings.HasPrefix(mediaType, "multipart/") {
		return r.ParseMultipartForm(formMemLimit)
	}
	return r.ParseForm()
}

// validateJobSizes enforces the per-field character caps for a job
// submission: the posted description and the stored career history.
func validateJobSizes(jobDescription, careerText string) error {
	if len(jobDescription) > MaxJobDescriptionChars {
		return fmt.Errorf("%w: over %d characters", ErrJobDescriptionTooLong, MaxJobDescriptionChars)
	}
	if len(careerText) > MaxCareerTextChars {
		return fmt.Errorf("%w: over %d characters", ErrCareerTextTooLong, MaxCareerTextChars)
	}
	return nil
}
