package web

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	natsjs "github.com/nats-io/nats.go/jetstream"
	"google.golang.org/protobuf/proto"

	eventsv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/events/v1"
	"github.com/corruptmane/cv/services/gateway/internal/jetstream"
	"github.com/corruptmane/cv/services/gateway/internal/store"
)

// StatusUpdate is the JSON payload of the SSE "status" event.
type StatusUpdate struct {
	Status      string  `json:"status"`
	Error       *string `json:"error"`
	DownloadURL *string `json:"download_url"`
}

// Terminal reports whether no further updates can follow.
func (u StatusUpdate) Terminal() bool {
	return u.Status == "completed" || u.Status == "failed"
}

func downloadURL(jobID string) *string {
	u := fmt.Sprintf("/jobs/%s/download", jobID)
	return &u
}

// statusRank orders statuses so replayed stream history can never move
// a client backwards; both terminal states share the top rank.
func statusRank(status string) int {
	switch status {
	case "pending":
		return 0
	case "rendering":
		return 1
	case "completed", "failed":
		return 2
	default:
		return -1
	}
}

// StatusFromJob maps the job's current database row to a StatusUpdate.
func StatusFromJob(job *store.Job) StatusUpdate {
	u := StatusUpdate{Status: job.Status, Error: job.Error}
	if job.Status == "completed" {
		u.DownloadURL = downloadURL(job.ID)
	}
	return u
}

// MapEvent maps one stream event (subject suffix + protobuf payload)
// to a StatusUpdate. ok is false for unknown event names.
func MapEvent(jobID, event string, payload []byte) (update StatusUpdate, ok bool, err error) {
	switch event {
	case jetstream.EventRequested:
		return StatusUpdate{Status: "pending"}, true, nil
	case jetstream.EventStructured:
		return StatusUpdate{Status: "rendering"}, true, nil
	case jetstream.EventRendered:
		return StatusUpdate{Status: "completed", DownloadURL: downloadURL(jobID)}, true, nil
	case jetstream.EventFailed:
		var ev eventsv1.JobFailed
		if err := proto.Unmarshal(payload, &ev); err != nil {
			return StatusUpdate{}, true, fmt.Errorf("unmarshal JobFailed: %w", err)
		}
		msg := ev.GetError()
		return StatusUpdate{Status: "failed", Error: &msg}, true, nil
	default:
		return StatusUpdate{}, false, nil
	}
}

const sseHeartbeat = 15 * time.Second

// handleJobEvents serves GET /jobs/:id/events: replays the job's event
// history via a per-connection ordered consumer and streams live
// updates until a terminal state or client disconnect.
func (s *Server) handleJobEvents(c *gin.Context) {
	job, ok := s.visitorJob(c)
	if !ok {
		return
	}

	w := c.Writer
	h := w.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	h.Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	// Current DB state first, so the client renders instantly.
	current := StatusFromJob(job)
	if err := writeSSE(w, current); err != nil {
		return
	}
	if current.Terminal() {
		return
	}
	lastRank := statusRank(current.Status)

	reqCtx := c.Request.Context()
	cons, err := jetstream.OrderedJobConsumer(reqCtx, s.js, job.ID)
	if err != nil {
		s.log.Error("create sse consumer", "job_id", job.ID, "error", err)
		return
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := jetstream.DeleteOrderedConsumer(ctx, s.js, cons); err != nil {
			s.log.Debug("delete sse consumer", "job_id", job.ID, "error", err)
		}
	}()

	type sseMsg struct {
		event   string
		payload []byte
	}
	msgs := make(chan sseMsg, 16)
	cc, err := cons.Consume(func(msg natsjs.Msg) {
		_, event, ok := jetstream.ParseSubject(msg.Subject())
		if !ok {
			return
		}
		select {
		case msgs <- sseMsg{event: event, payload: msg.Data()}:
		case <-reqCtx.Done():
		}
	})
	if err != nil {
		s.log.Error("start sse consume", "job_id", job.ID, "error", err)
		return
	}
	defer cc.Stop()

	heartbeat := time.NewTicker(sseHeartbeat)
	defer heartbeat.Stop()

	for {
		select {
		case <-reqCtx.Done():
			return
		case <-heartbeat.C:
			if _, err := io.WriteString(w, ": keep-alive\n\n"); err != nil {
				return
			}
			w.Flush()
		case m := <-msgs:
			update, known, err := MapEvent(job.ID, m.event, m.payload)
			if err != nil {
				s.log.Warn("map sse event", "job_id", job.ID, "event", m.event, "error", err)
				continue
			}
			if !known {
				continue
			}
			// The ordered consumer replays the job's full history
			// (DeliverAll closes the DB-read/consumer-start race); skip
			// anything that would move the client backwards or repeat
			// the state already sent.
			if rank := statusRank(update.Status); rank <= lastRank {
				continue
			} else {
				lastRank = rank
			}
			if err := writeSSE(w, update); err != nil {
				return
			}
			if update.Terminal() {
				return
			}
		}
	}
}

// writeSSE writes one named "status" event and flushes.
func writeSSE(w gin.ResponseWriter, update StatusUpdate) error {
	data, err := json.Marshal(update)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(w, "event: status\ndata: %s\n\n", data); err != nil {
		return err
	}
	w.Flush()
	return nil
}
