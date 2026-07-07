package httpapi

import (
	"html/template"
	"log/slog"
	"net/http"
	"strconv"

	cvv1 "github.com/corruptmane/cv/gen/go/cv/v1"
	"github.com/corruptmane/cv/services/gateway/internal/store"
	"github.com/corruptmane/cv/services/gateway/internal/telemetry"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func (s *Server) handleIndex(c *gin.Context) {
	// Seed the model dropdown with the default provider's (test) models.
	c.HTML(http.StatusOK, "index.html", gin.H{"Models": s.deps.Models.For("test")})
}

// handleModels returns the <select> of models for the chosen provider (HTMX
// swaps it into the form when the provider changes).
func (s *Server) handleModels(c *gin.Context) {
	c.HTML(http.StatusOK, "model_field", gin.H{"Models": s.deps.Models.For(c.Query("provider"))})
}

func (s *Server) handleCreate(c *gin.Context) {
	ctx := c.Request.Context()
	jobID := uuid.NewString()

	contacts := &cvv1.Contacts{
		Name:            c.PostForm("name"),
		Email:           c.PostForm("email"),
		LocationCity:    c.PostForm("location_city"),
		LocationCountry: c.PostForm("location_country"),
	}
	if phone := c.PostForm("phone"); phone != "" {
		contacts.Phone = &phone
	}
	labels := c.PostFormArray("link_label")
	urls := c.PostFormArray("link_url")
	for i := range labels {
		if labels[i] == "" || i >= len(urls) || urls[i] == "" {
			continue
		}
		contacts.Links = append(contacts.Links, &cvv1.Link{Label: labels[i], Url: urls[i]})
	}

	provider := providerFromForm(c.PostForm("provider"))
	// Validate the model against the registry; fall back to the provider default.
	model := s.deps.Models.Resolve(providerName(provider), c.PostForm("model"))
	req := &cvv1.GenerationRequest{
		JobId:          jobID,
		ExperienceText: c.PostForm("experience_text"),
		JobDescription: c.PostForm("job_description"),
		Contacts:       contacts,
		Provider:       provider,
		Model:          model,
	}

	// Transient BYO key: held in Valkey only, never on the bus / DB / logs.
	if err := s.deps.Secrets.Put(ctx, jobID, c.PostForm("api_key"), s.deps.Cfg.SecretTTL); err != nil {
		s.fail(c, "store key", err)
		return
	}

	// Insert the row BEFORE publishing: a fast pipeline can emit result events
	// (structured/completed) almost immediately, and gateway-persist must find
	// an existing row to update — otherwise the status projection is lost.
	contactsJSON, _ := protojson.Marshal(contacts)
	if _, err := s.deps.Store.Create(ctx, store.CreateParams{
		ID:             jobID,
		Provider:       providerName(provider),
		Model:          model,
		ExperienceText: req.ExperienceText,
		JobDescription: req.JobDescription,
		Contacts:       contactsJSON,
	}); err != nil {
		s.fail(c, "persist", err)
		return
	}

	data, err := proto.Marshal(req)
	if err != nil {
		s.fail(c, "marshal request", err)
		return
	}
	hdr := nats.Header{}
	telemetry.InjectNATS(ctx, hdr)
	if err := s.deps.Bus.Publish(ctx, "cv."+jobID+".requested", data, hdr); err != nil {
		s.fail(c, "publish", err)
		return
	}

	slog.InfoContext(ctx, "generation queued", "job_id", jobID, "provider", providerName(provider))
	c.Redirect(http.StatusSeeOther, "/generations/"+jobID)
}

func (s *Server) handleStatusPage(c *gin.Context) {
	gen, err := s.deps.Store.Get(c.Request.Context(), c.Param("id"))
	if err != nil {
		c.String(http.StatusNotFound, "not found")
		return
	}
	c.HTML(http.StatusOK, "status.html", gin.H{
		"ID":       gen.ID,
		"Fragment": template.HTML(s.renderStatus(gen.ID, statusKeyFromDB(gen.Status), gen.Error)),
	})
}

func (s *Server) handlePDF(c *gin.Context) {
	ctx := c.Request.Context()
	gen, err := s.deps.Store.Get(ctx, c.Param("id"))
	if err != nil {
		c.String(http.StatusNotFound, "not found")
		return
	}
	if gen.Status != store.StatusCompleted || gen.PdfObjectKey == "" {
		c.String(http.StatusConflict, "not ready")
		return
	}
	body, size, err := s.deps.Storage.Get(ctx, gen.PdfObjectKey)
	if err != nil {
		s.fail(c, "fetch pdf", err)
		return
	}
	defer body.Close()
	c.Header("Content-Disposition", `attachment; filename="cv-`+gen.ID+`.pdf"`)
	if size > 0 {
		c.Header("Content-Length", strconv.FormatInt(size, 10))
	}
	c.DataFromReader(http.StatusOK, size, "application/pdf", body, nil)
}

func (s *Server) fail(c *gin.Context, what string, err error) {
	slog.ErrorContext(c.Request.Context(), "request failed", "op", what, "error", err)
	c.String(http.StatusInternalServerError, "internal error")
}
