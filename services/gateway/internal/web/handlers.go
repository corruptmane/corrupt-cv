package web

import (
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/timestamppb"

	catalogv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/catalog/v1"
	cvv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/cv/v1"
	eventsv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/events/v1"
	"github.com/corruptmane/cv/services/gateway/internal/s3"
	"github.com/corruptmane/cv/services/gateway/internal/session"
	"github.com/corruptmane/cv/services/gateway/internal/store"
)

// profileForm is the flattened profile as shown in the index form.
type profileForm struct {
	CareerText string
	Name       string
	Email      string
	Phone      string
	City       string
	Country    string
	Links      string // one "Label https://url" per line
}

type indexData struct {
	Profile    profileForm
	HasProfile bool
	Jobs       []store.Job
	Models     []*catalogv1.ModelCatalogEntry
	Error      string
	Notice     string
}

type jobPageData struct {
	Job *store.Job
	// InitialJSON is the json.Marshal-ed StatusUpdate for the job's
	// current state, embedded raw in the page script. json.Marshal
	// HTML-escapes string contents, so it is safe inside <script>.
	InitialJSON template.JS
}

func redirectWithError(c *gin.Context, msg string) {
	c.Redirect(http.StatusSeeOther, "/?error="+url.QueryEscape(msg))
}

// handleIndex renders the profile form, job form, and job history.
func (s *Server) handleIndex(c *gin.Context) {
	visitor := session.VisitorID(c)
	data := indexData{
		Models: s.cat.All(),
		Error:  c.Query("error"),
		Notice: c.Query("notice"),
	}

	profile, err := s.st.GetProfile(c.Request.Context(), visitor)
	switch {
	case err == nil:
		data.HasProfile = true
		data.Profile = profileToForm(profile)
	case errors.Is(err, store.ErrNotFound):
		// first visit: empty form
	default:
		s.log.Error("load profile", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}

	jobs, err := s.st.ListJobs(c.Request.Context(), visitor, 20)
	if err != nil {
		s.log.Error("list jobs", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	data.Jobs = jobs

	c.Status(http.StatusOK)
	c.Header("Content-Type", "text/html; charset=utf-8")
	if err := s.tmplIndex.ExecuteTemplate(c.Writer, "base.html", data); err != nil {
		s.log.Error("render index", "error", err)
	}
}

func profileToForm(p *store.Profile) profileForm {
	form := profileForm{CareerText: p.CareerText}
	if len(p.PersonalInfo) == 0 {
		return form
	}
	var info cvv1.PersonalInfo
	if err := protojson.Unmarshal(p.PersonalInfo, &info); err != nil {
		return form
	}
	form.Name = info.GetName()
	form.Email = info.GetEmail()
	form.Phone = info.GetPhone()
	form.City = info.GetLocationCity()
	form.Country = info.GetLocationCountry()
	var lines []string
	for _, l := range info.GetLinks() {
		lines = append(lines, l.GetLabel()+" "+l.GetUrl())
	}
	form.Links = strings.Join(lines, "\n")
	return form
}

// parseLinks parses the links textarea: one "Label https://url" per
// line; the URL is the last whitespace-separated token.
func parseLinks(raw string) []*cvv1.Link {
	var links []*cvv1.Link
	for _, line := range strings.Split(raw, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		idx := strings.LastIndexAny(line, " \t")
		if idx < 0 {
			links = append(links, &cvv1.Link{Label: line, Url: line})
			continue
		}
		label := strings.TrimSpace(line[:idx])
		u := strings.TrimSpace(line[idx+1:])
		links = append(links, &cvv1.Link{Label: label, Url: u})
	}
	return links
}

// handleProfileSave upserts the visitor's profile from the form.
func (s *Server) handleProfileSave(c *gin.Context) {
	careerText := strings.TrimSpace(c.PostForm("career_text"))
	name := strings.TrimSpace(c.PostForm("name"))
	email := strings.TrimSpace(c.PostForm("email"))

	if careerText == "" {
		redirectWithError(c, "Career history must not be empty.")
		return
	}
	if name == "" || email == "" {
		redirectWithError(c, "Name and email are required.")
		return
	}

	info := &cvv1.PersonalInfo{
		Name:            name,
		Email:           email,
		LocationCity:    strings.TrimSpace(c.PostForm("city")),
		LocationCountry: strings.TrimSpace(c.PostForm("country")),
		Links:           parseLinks(c.PostForm("links")),
	}
	if phone := strings.TrimSpace(c.PostForm("phone")); phone != "" {
		info.Phone = &phone
	}

	infoJSON, err := protojson.Marshal(info)
	if err != nil {
		s.log.Error("encode personal info", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	if err := s.st.UpsertProfile(c.Request.Context(), session.VisitorID(c), careerText, infoJSON); err != nil {
		s.log.Error("save profile", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	c.Redirect(http.StatusSeeOther, "/?notice="+url.QueryEscape("Profile saved."))
}

// handleJobCreate validates the job form, creates the job row, hands
// the API key to Valkey, publishes JobRequested, and redirects to the
// job page.
func (s *Server) handleJobCreate(c *gin.Context) {
	ctx := c.Request.Context()
	visitor := session.VisitorID(c)

	jobDescription := strings.TrimSpace(c.PostForm("job_description"))
	modelKey := strings.TrimSpace(c.PostForm("model_key"))
	apiKey := strings.TrimSpace(c.PostForm("api_key"))

	if jobDescription == "" {
		redirectWithError(c, "Job description must not be empty.")
		return
	}
	entry := s.cat.Get(modelKey)
	if entry == nil {
		redirectWithError(c, "Please pick a model from the list.")
		return
	}
	if entry.GetProvider() != catalogv1.Provider_PROVIDER_FAKE && apiKey == "" {
		redirectWithError(c, "This model requires your provider API key.")
		return
	}

	profile, err := s.st.GetProfile(ctx, visitor)
	if errors.Is(err, store.ErrNotFound) {
		redirectWithError(c, "Save your profile before generating a CV.")
		return
	}
	if err != nil {
		s.log.Error("load profile", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	if strings.TrimSpace(profile.CareerText) == "" || len(profile.PersonalInfo) == 0 {
		redirectWithError(c, "Your profile needs career history and personal details first.")
		return
	}
	var personalInfo cvv1.PersonalInfo
	if err := protojson.Unmarshal(profile.PersonalInfo, &personalInfo); err != nil {
		s.log.Error("decode personal info", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}

	jobID, err := s.st.CreateJob(ctx, visitor, profile.ID, jobDescription, modelKey)
	if err != nil {
		s.log.Error("create job", "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	log := s.log.With("job_id", jobID)

	// The key goes to Valkey BEFORE the event is published so the
	// processor can never observe the event without the key.
	if apiKey != "" {
		if err := s.keys.Put(ctx, jobID, apiKey); err != nil {
			log.ErrorContext(ctx, "store api key", "error", err)
			_, _, _ = s.st.MarkFailed(ctx, jobID, "could not hand off API key")
			c.Redirect(http.StatusSeeOther, "/jobs/"+jobID)
			return
		}
	}

	ev := &eventsv1.JobRequested{
		JobId:          jobID,
		CareerText:     profile.CareerText,
		JobDescription: jobDescription,
		PersonalInfo:   &personalInfo,
		ModelKey:       modelKey,
		OccurredAt:     timestamppb.Now(),
	}
	if err := s.pub.PublishJobRequested(ctx, ev); err != nil {
		log.ErrorContext(ctx, "publish JobRequested", "error", err)
		_, _, _ = s.st.MarkFailed(ctx, jobID, "could not enqueue job")
	}
	c.Redirect(http.StatusSeeOther, "/jobs/"+jobID)
}

// handleJobPage renders the job progress page.
func (s *Server) handleJobPage(c *gin.Context) {
	job, ok := s.visitorJob(c)
	if !ok {
		return
	}
	initial, err := json.Marshal(StatusFromJob(job))
	if err != nil {
		s.log.Error("encode initial status", "job_id", job.ID, "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	c.Status(http.StatusOK)
	c.Header("Content-Type", "text/html; charset=utf-8")
	data := jobPageData{Job: job, InitialJSON: template.JS(initial)}
	if err := s.tmplJob.ExecuteTemplate(c.Writer, "base.html", data); err != nil {
		s.log.Error("render job page", "job_id", job.ID, "error", err)
	}
}

// handleJobDownload streams the rendered PDF from object storage.
func (s *Server) handleJobDownload(c *gin.Context) {
	job, ok := s.visitorJob(c)
	if !ok {
		return
	}
	if job.Status != "completed" || job.PDFObjectKey == nil {
		c.String(http.StatusNotFound, "PDF not available")
		return
	}
	obj, err := s.objects.Get(c.Request.Context(), *job.PDFObjectKey)
	if err != nil {
		if errors.Is(err, s3.ErrNotFound) {
			c.String(http.StatusNotFound, "PDF not available")
			return
		}
		s.log.Error("fetch pdf", "job_id", job.ID, "error", err)
		c.String(http.StatusInternalServerError, "internal error")
		return
	}
	defer func() { _ = obj.Body.Close() }()

	c.Header("Content-Type", "application/pdf")
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=%q", "cv-"+job.ID+".pdf"))
	if obj.ContentLength != nil {
		c.Header("Content-Length", strconv.FormatInt(*obj.ContentLength, 10))
	}
	c.Status(http.StatusOK)
	if _, err := io.Copy(c.Writer, obj.Body); err != nil {
		s.log.Warn("stream pdf interrupted", "job_id", job.ID, "error", err)
	}
}

// handleJobAPI serves the JSON job state used by e2e polling.
func (s *Server) handleJobAPI(c *gin.Context) {
	job, ok := s.visitorJob(c)
	if !ok {
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"id":             job.ID,
		"status":         job.Status,
		"error":          job.Error,
		"pdf_object_key": job.PDFObjectKey,
	})
}

// handleModelSearch renders the HTMX active-search partial.
func (s *Server) handleModelSearch(c *gin.Context) {
	results := s.cat.Search(c.Query("q"))
	c.Status(http.StatusOK)
	c.Header("Content-Type", "text/html; charset=utf-8")
	if err := s.tmplSearch.ExecuteTemplate(c.Writer, "models_search.html", results); err != nil {
		s.log.Error("render model search", "error", err)
	}
}
