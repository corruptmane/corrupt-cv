// Business-funnel instruments for the web package. They come from the
// global MeterProvider installed by telemetry.Setup; when telemetry is
// off they are no-ops.
package web

import (
	"context"
	"log/slog"
	"sync/atomic"

	"github.com/gin-gonic/gin"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	"github.com/corruptmane/corrupt-cv/services/gateway/internal/telemetry"
)

// Rejection reasons on cvgen.jobs.rejected.total — the funnel between
// the job form and a created job row.
const (
	reasonEmptyDescription  = "empty_description"
	reasonUnknownModel      = "unknown_model"
	reasonMissingAPIKey     = "missing_api_key"
	reasonNoProfile         = "no_profile"
	reasonJobTooLong        = "job_too_long"
	reasonCareerTooLong     = "career_too_long"
	reasonIncompleteProfile = "incomplete_profile"
)

// webMetrics holds the gateway's business instruments plus the counter
// backing the SSE active-connections gauge.
type webMetrics struct {
	jobsCreated    metric.Int64Counter
	jobsRejected   metric.Int64Counter
	profilesSaved  metric.Int64Counter
	downloads      metric.Int64Counter
	downloadBytes  metric.Int64Histogram
	sseStreams     metric.Int64Counter
	sseActive      metric.Int64ObservableGauge
	sseConnections atomic.Int64
}

func newWebMetrics(log *slog.Logger) *webMetrics {
	meter := otel.Meter(telemetry.ScopeName)
	m := &webMetrics{
		jobsCreated: telemetry.Int64Counter(meter, "cvgen.jobs.created.total",
			metric.WithDescription("Job rows created, by model.")),
		jobsRejected: telemetry.Int64Counter(meter, "cvgen.jobs.rejected.total",
			metric.WithDescription("Job submissions rejected before a row was created, by validation reason.")),
		profilesSaved: telemetry.Int64Counter(meter, "cvgen.profiles.saved.total",
			metric.WithDescription("Career profile upserts.")),
		downloads: telemetry.Int64Counter(meter, "cvgen.jobs.downloads.total",
			metric.WithDescription("Completed-CV PDF downloads served.")),
		downloadBytes: telemetry.Int64Histogram(meter, "cvgen.download.bytes",
			metric.WithUnit("By"),
			metric.WithDescription("Served PDF sizes."),
			metric.WithExplicitBucketBoundaries(10_240, 102_400, 1_048_576, 5_242_880)),
		sseStreams: telemetry.Int64Counter(meter, "cvgen.sse.streams.total",
			metric.WithDescription("SSE job-event streams opened.")),
		sseActive: telemetry.Int64ObservableGauge(meter, "cvgen.sse.active",
			metric.WithDescription("Currently open SSE job-event streams.")),
	}
	if _, err := meter.RegisterCallback(func(_ context.Context, o metric.Observer) error {
		o.ObserveInt64(m.sseActive, m.sseConnections.Load())
		return nil
	}, m.sseActive); err != nil {
		log.Warn("register cvgen.sse.active callback", "error", err)
	}
	return m
}

// rejectJob counts a rejected submission and emits its user-safe flash.
func (s *Server) rejectJob(c *gin.Context, reason, msg string) {
	s.metrics.jobsRejected.Add(c.Request.Context(), 1,
		metric.WithAttributes(attribute.String("reason", reason)))
	redirectWithError(c, msg)
}
