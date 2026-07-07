// Package httpapi is the Gin HTTP surface: HTMX form, SSE status stream, and
// PDF download.
package httpapi

import (
	"html/template"
	"io/fs"
	"net/http"

	"github.com/corruptmane/cv/services/gateway/internal/bus"
	"github.com/corruptmane/cv/services/gateway/internal/config"
	"github.com/corruptmane/cv/services/gateway/internal/modelcfg"
	"github.com/corruptmane/cv/services/gateway/internal/secrets"
	"github.com/corruptmane/cv/services/gateway/internal/storage"
	"github.com/corruptmane/cv/services/gateway/internal/store"
	"github.com/corruptmane/cv/services/gateway/web"
	"github.com/gin-gonic/gin"
	"go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"
)

type Deps struct {
	Store   *store.Store
	Secrets *secrets.Store
	Storage *storage.Store
	Bus     *bus.Bus
	Models  *modelcfg.Registry
	Cfg     config.Config
}

type Server struct {
	deps   Deps
	engine *gin.Engine
	tmpl   *template.Template
}

func New(deps Deps) *Server {
	tmpl := template.Must(template.ParseFS(web.FS, "templates/*.html"))

	engine := gin.New()
	engine.Use(gin.Recovery(), otelgin.Middleware(deps.Cfg.ServiceName))
	engine.SetHTMLTemplate(tmpl)

	staticFS, _ := fs.Sub(web.FS, "static")
	engine.StaticFS("/static", http.FS(staticFS))

	s := &Server{deps: deps, engine: engine, tmpl: tmpl}
	engine.GET("/", s.handleIndex)
	engine.GET("/models", s.handleModels)
	engine.POST("/generations", s.handleCreate)
	engine.GET("/generations/:id", s.handleStatusPage)
	engine.GET("/generations/:id/events", s.handleEvents)
	engine.GET("/generations/:id/pdf", s.handlePDF)
	return s
}

func (s *Server) Engine() *gin.Engine { return s.engine }
