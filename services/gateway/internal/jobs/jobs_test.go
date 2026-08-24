package jobs

import (
	"testing"

	"github.com/nats-io/nats.go"
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
