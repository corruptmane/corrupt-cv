package jobs

import (
	"context"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	oteltrace "go.opentelemetry.io/otel/trace"

	"github.com/corruptmane/corrupt-cv/services/gateway/internal/telemetry"
)

// fakeSubscriber records how the advisory subscription is registered.
type fakeSubscriber struct {
	subject    string
	queue      string
	hasHandler bool
}

func (f *fakeSubscriber) QueueSubscribe(subj, queue string, cb nats.MsgHandler) (*nats.Subscription, error) {
	f.subject = subj
	f.queue = queue
	f.hasHandler = cb != nil
	return nil, nil
}

// The advisory watch must be a queue-grouped subscription so gateway
// replicas share advisory delivery instead of every replica reacting
// to the same poisoned job.
func TestSubscribeAdvisoryUsesQueueGroup(t *testing.T) {
	fake := &fakeSubscriber{}
	if _, err := subscribeAdvisory(fake, func(*nats.Msg) {}); err != nil {
		t.Fatalf("subscribeAdvisory: %v", err)
	}
	if fake.subject != advisorySubject {
		t.Errorf("subject = %q, want %q", fake.subject, advisorySubject)
	}
	if fake.queue != advisoryQueueGroup {
		t.Errorf("queue group = %q, want %q", fake.queue, advisoryQueueGroup)
	}
	if !fake.hasHandler {
		t.Error("subscription must carry a message handler")
	}
}

func TestAdvisoryQueueGroupName(t *testing.T) {
	if advisoryQueueGroup != "cvgen-advisories" {
		t.Fatalf("advisoryQueueGroup = %q, want cvgen-advisories", advisoryQueueGroup)
	}
}

// recordTerminal must emit one terminal-status counter increment and one
// duration observation, both carrying the status attribute.
func TestRecordTerminalRecordsStatusAndDuration(t *testing.T) {
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = mp.Shutdown(context.Background()) })
	meter := mp.Meter(telemetry.ScopeName)

	r := &Runner{
		tracer: oteltrace.NewNoopTracerProvider().Tracer("test"),
		jobsTotal: telemetry.Int64Counter(meter, "cvgen.jobs.total",
			metric.WithDescription("Jobs that reached a terminal status.")),
		jobDuration: telemetry.Float64Histogram(meter, "cvgen.job.duration", metric.WithUnit("s")),
	}

	createdAt := time.Now().Add(-30 * time.Second)
	r.recordTerminal(context.Background(), "completed", createdAt, nil)

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("collect: %v", err)
	}
	var sum int64
	var histogramSum float64
	var count uint64
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			switch m.Name {
			case "cvgen.jobs.total":
				data := m.Data.(metricdata.Sum[int64])
				for _, dp := range data.DataPoints {
					sum += dp.Value
					if got := dp.Attributes.ToSlice(); len(got) == 1 && got[0].Key == "status" && got[0].Value.AsString() != "completed" {
						t.Errorf("status attr = %q, want completed", got[0].Value.AsString())
					}
				}
			case "cvgen.job.duration":
				data := m.Data.(metricdata.Histogram[float64])
				for _, dp := range data.DataPoints {
					count = dp.Count
					histogramSum = dp.Sum
				}
			}
		}
	}
	if sum != 1 {
		t.Errorf("cvgen.jobs.total sum = %d, want 1", sum)
	}
	if count != 1 {
		t.Fatalf("cvgen.job.duration count = %d, want 1", count)
	}
	// occurredAt is nil so the duration ends at now (~30s after createdAt).
	if histogramSum < 25 || histogramSum > 60 {
		t.Errorf("cvgen.job.duration sum = %v, want ~30", histogramSum)
	}
}
