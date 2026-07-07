package httpapi

import (
	"io"
	"net/http"
	"sync"

	cvv1 "github.com/corruptmane/cv/gen/go/cv/v1"
	"github.com/gin-gonic/gin"
	"github.com/nats-io/nats.go/jetstream"
	"google.golang.org/protobuf/proto"
)

type sseMsg struct {
	html string
	last bool
}

// handleEvents streams a job's status to the browser as Server-Sent Events.
// It seeds the current DB state, then live-tails the per-job NATS subject via
// an ephemeral consumer until a terminal event.
func (s *Server) handleEvents(c *gin.Context) {
	id := c.Param("id")
	gen, err := s.deps.Store.Get(c.Request.Context(), id)
	if err != nil {
		c.String(http.StatusNotFound, "not found")
		return
	}

	c.Writer.Header().Set("Content-Type", "text/event-stream")
	c.Writer.Header().Set("Cache-Control", "no-cache")
	c.Writer.Header().Set("Connection", "keep-alive")
	c.Writer.Header().Set("X-Accel-Buffering", "no")

	ch := make(chan sseMsg, 16)
	var once sync.Once
	done := func() { once.Do(func() { close(ch) }) }

	initial := statusKeyFromDB(gen.Status)
	ch <- sseMsg{html: s.renderStatus(id, initial, gen.Error), last: terminal(initial)}

	cc, err := s.deps.Bus.JobEvents(c.Request.Context(), id, func(msg jetstream.Msg) {
		_ = msg.Ack()
		key := statusKeyFromSubject(msg.Subject())
		errMsg := ""
		if key == "failed" {
			var ev cvv1.CVFailed
			if proto.Unmarshal(msg.Data(), &ev) == nil {
				errMsg = ev.Message
			}
		}
		select {
		case ch <- sseMsg{html: s.renderStatus(id, key, errMsg), last: terminal(key)}:
		default:
		}
		if terminal(key) {
			done()
		}
	})
	if err != nil {
		c.String(http.StatusInternalServerError, "stream error")
		return
	}
	defer cc.Stop()

	c.Stream(func(w io.Writer) bool {
		m, ok := <-ch
		if !ok {
			return false
		}
		c.SSEvent("status", m.html)
		return !m.last
	})
}
