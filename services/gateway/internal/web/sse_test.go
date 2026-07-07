package web

import (
	"testing"

	"google.golang.org/protobuf/proto"

	eventsv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/events/v1"
	"github.com/corruptmane/cv/services/gateway/internal/store"
)

const testJobID = "3fa9f34a-6a7d-4a1f-9df0-1c2b3d4e5f60"

func TestMapEventRequested(t *testing.T) {
	u, ok, err := MapEvent(testJobID, "requested", nil)
	if err != nil || !ok {
		t.Fatalf("MapEvent(requested) ok=%v err=%v", ok, err)
	}
	if u.Status != "pending" || u.Error != nil || u.DownloadURL != nil {
		t.Fatalf("MapEvent(requested) = %+v, want pending with nil error/url", u)
	}
	if u.Terminal() {
		t.Error("pending must not be terminal")
	}
}

func TestMapEventStructured(t *testing.T) {
	u, ok, err := MapEvent(testJobID, "structured", nil)
	if err != nil || !ok {
		t.Fatalf("MapEvent(structured) ok=%v err=%v", ok, err)
	}
	if u.Status != "rendering" || u.DownloadURL != nil {
		t.Fatalf("MapEvent(structured) = %+v, want rendering", u)
	}
	if u.Terminal() {
		t.Error("rendering must not be terminal")
	}
}

func TestMapEventRendered(t *testing.T) {
	u, ok, err := MapEvent(testJobID, "rendered", nil)
	if err != nil || !ok {
		t.Fatalf("MapEvent(rendered) ok=%v err=%v", ok, err)
	}
	if u.Status != "completed" {
		t.Fatalf("status = %q, want completed", u.Status)
	}
	want := "/jobs/" + testJobID + "/download"
	if u.DownloadURL == nil || *u.DownloadURL != want {
		t.Fatalf("download_url = %v, want %q", u.DownloadURL, want)
	}
	if !u.Terminal() {
		t.Error("completed must be terminal")
	}
}

func TestMapEventFailed(t *testing.T) {
	payload, err := proto.Marshal(&eventsv1.JobFailed{
		JobId: testJobID,
		Stage: eventsv1.JobStage_JOB_STAGE_PROCESSING,
		Error: "the model refused",
	})
	if err != nil {
		t.Fatal(err)
	}
	u, ok, err := MapEvent(testJobID, "failed", payload)
	if err != nil || !ok {
		t.Fatalf("MapEvent(failed) ok=%v err=%v", ok, err)
	}
	if u.Status != "failed" {
		t.Fatalf("status = %q, want failed", u.Status)
	}
	if u.Error == nil || *u.Error != "the model refused" {
		t.Fatalf("error = %v, want the event error", u.Error)
	}
	if u.DownloadURL != nil {
		t.Error("failed update must not carry a download url")
	}
	if !u.Terminal() {
		t.Error("failed must be terminal")
	}
}

func TestMapEventUnknown(t *testing.T) {
	_, ok, err := MapEvent(testJobID, "reticulated", nil)
	if ok || err != nil {
		t.Fatalf("MapEvent(unknown) ok=%v err=%v, want ok=false err=nil", ok, err)
	}
}

func TestStatusFromJob(t *testing.T) {
	errText := "boom"
	cases := []struct {
		name    string
		job     store.Job
		status  string
		withURL bool
		withErr bool
	}{
		{"pending", store.Job{ID: testJobID, Status: "pending"}, "pending", false, false},
		{"rendering", store.Job{ID: testJobID, Status: "rendering"}, "rendering", false, false},
		{"completed", store.Job{ID: testJobID, Status: "completed"}, "completed", true, false},
		{"failed", store.Job{ID: testJobID, Status: "failed", Error: &errText}, "failed", false, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			u := StatusFromJob(&tc.job)
			if u.Status != tc.status {
				t.Fatalf("status = %q, want %q", u.Status, tc.status)
			}
			if (u.DownloadURL != nil) != tc.withURL {
				t.Fatalf("download_url = %v, withURL = %v", u.DownloadURL, tc.withURL)
			}
			if (u.Error != nil) != tc.withErr {
				t.Fatalf("error = %v, withErr = %v", u.Error, tc.withErr)
			}
		})
	}
}
