// Package web serves the HTML UI and job API: profile and job forms,
// the HTMX model search partial, the SSE progress stream, and the PDF
// download.
package web

import (
	"embed"
	"errors"
	"html/template"
	"io/fs"
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	natsjs "github.com/nats-io/nats.go/jetstream"
	"go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"

	"github.com/corruptmane/cv/services/gateway/internal/apikeys"
	"github.com/corruptmane/cv/services/gateway/internal/catalog"
	"github.com/corruptmane/cv/services/gateway/internal/jetstream"
	"github.com/corruptmane/cv/services/gateway/internal/s3"
	"github.com/corruptmane/cv/services/gateway/internal/session"
	"github.com/corruptmane/cv/services/gateway/internal/store"
)

//go:embed templates/*.html
var templateFS embed.FS

//go:embed static
var staticFS embed.FS

// Server wires the web handlers to their dependencies.
type Server struct {
	st      *store.Store
	cat     *catalog.Catalog
	js      natsjs.JetStream
	pub     *jetstream.Publisher
	keys    *apikeys.Store
	objects *s3.Client
	log     *slog.Logger

	tmplIndex  *template.Template
	tmplJob    *template.Template
	tmplSearch *template.Template
}

// New builds the Server and parses the embedded templates.
func New(st *store.Store, cat *catalog.Catalog, js natsjs.JetStream, pub *jetstream.Publisher,
	keys *apikeys.Store, objects *s3.Client, log *slog.Logger) *Server {
	return &Server{
		st:      st,
		cat:     cat,
		js:      js,
		pub:     pub,
		keys:    keys,
		objects: objects,
		log:     log,

		tmplIndex:  template.Must(template.ParseFS(templateFS, "templates/base.html", "templates/index.html")),
		tmplJob:    template.Must(template.ParseFS(templateFS, "templates/base.html", "templates/job.html")),
		tmplSearch: template.Must(template.ParseFS(templateFS, "templates/models_search.html")),
	}
}

// Router builds the gin engine with the session middleware and all
// application routes. When tracing is true (telemetry enabled) each
// request runs under an otelgin server span — the POST /jobs span is
// the root of the whole pipeline trace. Static assets are excluded.
func (s *Server) Router(sessionSecret []byte, tracing bool) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	if tracing {
		r.Use(otelgin.Middleware("gateway", otelgin.WithFilter(func(req *http.Request) bool {
			return !strings.HasPrefix(req.URL.Path, "/static/")
		})))
	}
	r.Use(s.requestLogger())
	r.Use(session.Middleware(sessionSecret))

	staticSub, err := fs.Sub(staticFS, "static")
	if err != nil {
		panic(err) // embed layout is fixed at compile time
	}
	r.StaticFS("/static", http.FS(staticSub))

	r.GET("/", s.handleIndex)
	r.POST("/profile", s.handleProfileSave)
	r.POST("/jobs", s.handleJobCreate)
	r.GET("/jobs/:id", s.handleJobPage)
	r.GET("/jobs/:id/events", s.handleJobEvents)
	r.GET("/jobs/:id/download", s.handleJobDownload)
	r.GET("/api/jobs/:id", s.handleJobAPI)
	r.GET("/models/search", s.handleModelSearch)

	return r
}

// requestLogger emits one slog line per request (skipping static
// assets and the long-lived SSE endpoint's completion noise).
func (s *Server) requestLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		path := c.Request.URL.Path
		c.Next()
		if strings.HasPrefix(path, "/static/") {
			return
		}
		s.log.InfoContext(c.Request.Context(), "http request",
			"method", c.Request.Method,
			"path", path,
			"status", c.Writer.Status(),
		)
	}
}

// visitorJob loads the job from the path parameter, enforcing visitor
// ownership. It writes the error response itself when returning false.
func (s *Server) visitorJob(c *gin.Context) (*store.Job, bool) {
	id := c.Param("id")
	if _, err := uuid.Parse(id); err != nil {
		c.String(http.StatusNotFound, "job not found")
		return nil, false
	}
	job, err := s.st.GetJob(c.Request.Context(), id, session.VisitorID(c))
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			c.String(http.StatusNotFound, "job not found")
		} else {
			s.log.Error("load job", "job_id", id, "error", err)
			c.String(http.StatusInternalServerError, "internal error")
		}
		return nil, false
	}
	return job, true
}
