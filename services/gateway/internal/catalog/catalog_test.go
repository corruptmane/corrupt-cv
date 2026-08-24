package catalog

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	natsjs "github.com/nats-io/nats.go/jetstream"

	catalogv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/catalog/v1"
)

const testYAML = `models:
  - key: fake/canned-cv
    provider: FAKE
    model_id: canned-cv
    display_name: Fake (canned CV)
    description: Returns a fixed example CV.
  - key: anthropic/claude-sonnet-4-5
    provider: ANTHROPIC
    model_id: claude-sonnet-4-5
    display_name: Claude Sonnet 4.5
  - key: anthropic/claude-haiku-4-5
    provider: ANTHROPIC
    model_id: claude-haiku-4-5
    display_name: Claude Haiku 4.5
  - key: openai/gpt-5.1
    provider: OPENAI
    model_id: gpt-5.1
    display_name: GPT-5.1
`

func loadTestCatalog(t *testing.T) *Catalog {
	t.Helper()
	path := filepath.Join(t.TempDir(), "catalog.yaml")
	if err := os.WriteFile(path, []byte(testYAML), 0o644); err != nil {
		t.Fatal(err)
	}
	c, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	return c
}

func keys(entries []*catalogv1.ModelCatalogEntry) []string {
	out := make([]string, len(entries))
	for i, e := range entries {
		out[i] = e.GetKey()
	}
	return out
}

func TestLoadParsesEntries(t *testing.T) {
	c := loadTestCatalog(t)
	if len(c.All()) != 4 {
		t.Fatalf("got %d entries, want 4", len(c.All()))
	}
	fake := c.Get("fake/canned-cv")
	if fake == nil {
		t.Fatal("Get(fake/canned-cv) returned nil")
	}
	if fake.GetProvider() != catalogv1.Provider_PROVIDER_FAKE {
		t.Errorf("provider = %v, want PROVIDER_FAKE", fake.GetProvider())
	}
	if fake.GetDescription() == "" {
		t.Error("description not parsed")
	}
	sonnet := c.Get("anthropic/claude-sonnet-4-5")
	if sonnet.GetProvider() != catalogv1.Provider_PROVIDER_ANTHROPIC {
		t.Errorf("provider = %v, want PROVIDER_ANTHROPIC", sonnet.GetProvider())
	}
	if sonnet.Description != nil {
		t.Error("description should be unset when absent from YAML")
	}
}

func TestSearchEmptyQueryReturnsAllInOrder(t *testing.T) {
	c := loadTestCatalog(t)
	got := keys(c.Search("   "))
	want := []string{"fake/canned-cv", "anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5", "openai/gpt-5.1"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

func TestSearchCaseInsensitiveSubstring(t *testing.T) {
	c := loadTestCatalog(t)
	got := keys(c.Search("CLAUDE"))
	if len(got) != 2 {
		t.Fatalf("Search(CLAUDE) = %v, want 2 claude entries", got)
	}
	if got[0] != "anthropic/claude-sonnet-4-5" || got[1] != "anthropic/claude-haiku-4-5" {
		t.Fatalf("Search(CLAUDE) = %v, wrong entries or order", got)
	}
}

func TestSearchSubsequenceMatch(t *testing.T) {
	c := loadTestCatalog(t)
	// "gpt51" is a non-contiguous subsequence of "openai/gpt-5.1".
	got := keys(c.Search("gpt51"))
	if len(got) != 1 || got[0] != "openai/gpt-5.1" {
		t.Fatalf("Search(gpt51) = %v, want [openai/gpt-5.1]", got)
	}
}

func TestSearchNoMatch(t *testing.T) {
	c := loadTestCatalog(t)
	if got := c.Search("zzzzzz"); len(got) != 0 {
		t.Fatalf("Search(zzzzzz) = %v, want empty", keys(got))
	}
}

func TestSearchMatchesDisplayName(t *testing.T) {
	c := loadTestCatalog(t)
	got := keys(c.Search("canned cv"))
	if len(got) != 1 || got[0] != "fake/canned-cv" {
		t.Fatalf("Search(canned cv) = %v, want [fake/canned-cv]", got)
	}
}

func loadInlineYAML(t *testing.T, yamlBody string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "catalog.yaml")
	if err := os.WriteFile(path, []byte(yamlBody), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadProviderMapping(t *testing.T) {
	cases := []struct {
		provider string
		wantOK   bool
	}{
		{"FAKE", true},
		{"ANTHROPIC", true},
		{"OPENROUTER", true},
		{"WIDGET", false},
	}
	for _, tc := range cases {
		yamlBody := fmt.Sprintf(`models:
  - key: test/model
    provider: %s
    model_id: model
    display_name: Test Model
`, tc.provider)
		c, err := Load(loadInlineYAML(t, yamlBody))
		if tc.wantOK {
			if err != nil {
				t.Errorf("provider %s: Load: %v, want ok", tc.provider, err)
				continue
			}
			entry := c.Get("test/model")
			if entry == nil {
				t.Errorf("provider %s: Get(test/model) returned nil", tc.provider)
				continue
			}
			if got := entry.GetProvider().String(); got != "PROVIDER_"+tc.provider {
				t.Errorf("provider %s: entry provider = %q, want PROVIDER_%s", tc.provider, got, tc.provider)
			}
		} else {
			if err == nil {
				t.Errorf("provider %s: Load succeeded, want unknown-provider error", tc.provider)
			}
		}
	}
}

func TestLoadRealCatalogFile(t *testing.T) {
	c, err := Load(filepath.Join("..", "..", "..", "..", "configs", "model-catalog.yaml"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	entries := c.All()
	if len(entries) < 13 {
		t.Fatalf("got %d entries, want >= 13", len(entries))
	}
	glm := c.Get("openrouter/glm-5.3")
	if glm == nil {
		t.Fatal("Get(openrouter/glm-5.3) returned nil")
	}
	if glm.GetModelId() != "z-ai/glm-5.3" {
		t.Errorf("model_id = %q, want z-ai/glm-5.3", glm.GetModelId())
	}
	for _, e := range entries {
		if strings.Contains(e.GetKey(), ":") {
			t.Errorf("key %q contains ':' (invalid in NATS KV keys)", e.GetKey())
		}
		if e.GetProvider() == catalogv1.Provider_PROVIDER_UNSPECIFIED {
			t.Errorf("entry %q has unspecified provider", e.GetKey())
		}
	}
}

func TestIsSubsequence(t *testing.T) {
	cases := []struct {
		needle, haystack string
		want             bool
	}{
		{"", "anything", true},
		{"abc", "abc", true},
		{"abc", "a-b-c", true},
		{"abc", "acb", false},
		{"abc", "ab", false},
	}
	for _, tc := range cases {
		if got := isSubsequence(tc.needle, tc.haystack); got != tc.want {
			t.Errorf("isSubsequence(%q, %q) = %v, want %v", tc.needle, tc.haystack, got, tc.want)
		}
	}
}

// fakeKV is an in-memory natsjs.KeyValue fake recording Put and Delete
// calls. Only the methods Seed uses are implemented; the embedded nil
// interface panics on anything else, which keeps the fake honest about
// which parts of the official interface catalog actually exercises.
type fakeKV struct {
	natsjs.KeyValue

	data    map[string][]byte
	puts    []string
	deletes []string
	rev     uint64
}

func newFakeKV(preset ...string) *fakeKV {
	f := &fakeKV{data: make(map[string][]byte, len(preset))}
	for _, k := range preset {
		f.data[k] = []byte("stale")
	}
	return f
}

func (f *fakeKV) Put(_ context.Context, key string, value []byte) (uint64, error) {
	f.rev++
	f.puts = append(f.puts, key)
	f.data[key] = value
	return f.rev, nil
}

func (f *fakeKV) Delete(_ context.Context, key string, _ ...natsjs.KVDeleteOpt) error {
	f.deletes = append(f.deletes, key)
	delete(f.data, key)
	return nil
}

func (f *fakeKV) Keys(context.Context, ...natsjs.WatchOpt) ([]string, error) {
	if len(f.data) == 0 {
		return nil, natsjs.ErrNoKeysFound
	}
	keys := make([]string, 0, len(f.data))
	for k := range f.data {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys, nil
}

func (f *fakeKV) Bucket() string { return "model-catalog" }

// captureLogs redirects the default slog logger into a buffer for the
// duration of the test (main.go installs the real logger via
// slog.SetDefault; this mirrors that wiring).
func captureLogs(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	prev := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&buf, nil)))
	t.Cleanup(func() { slog.SetDefault(prev) })
	return &buf
}

func TestSeedEvictsStaleKeys(t *testing.T) {
	logs := captureLogs(t)
	kv := newFakeKV("fake/canned-cv", "ghost/old-model")
	c, err := Load(loadInlineYAML(t, `models:
  - key: fake/canned-cv
    provider: FAKE
    model_id: canned-cv
    display_name: Fake (canned CV)
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if err := c.Seed(context.Background(), kv); err != nil {
		t.Fatalf("Seed: %v", err)
	}

	if len(kv.deletes) != 1 || kv.deletes[0] != "ghost/old-model" {
		t.Fatalf("deletes = %v, want exactly [ghost/old-model]", kv.deletes)
	}
	survivorPut := false
	for _, k := range kv.puts {
		if k == "fake/canned-cv" {
			survivorPut = true
		}
		if k == "ghost/old-model" {
			t.Errorf("ghost/old-model must be deleted, not upserted")
		}
	}
	if !survivorPut {
		t.Errorf("puts = %v, want survivor fake/canned-cv upserted", kv.puts)
	}
	for _, d := range kv.deletes {
		if d == "fake/canned-cv" {
			t.Errorf("survivor fake/canned-cv must not be deleted")
		}
	}
	if _, ok := kv.data["ghost/old-model"]; ok {
		t.Error("ghost/old-model still present in KV after Seed")
	}
	if _, ok := kv.data["fake/canned-cv"]; !ok {
		t.Error("fake/canned-cv missing from KV after Seed")
	}
	if !strings.Contains(logs.String(), "ghost/old-model") {
		t.Errorf("eviction of ghost/old-model not logged, logs:\n%s", logs.String())
	}
}

func TestLoadRejectsInvalidKeyCharset(t *testing.T) {
	cases := []struct{ name, key, wantErr string }{
		{"colon", "bad:key", `model "bad:key": invalid character ":" at position 4`},
		{"space", "bad key", `model "bad key": invalid character " " at position 4`},
		{"non-ascii", "ok/café", `model "ok/café": invalid character "é" at position 7`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			path := loadInlineYAML(t, fmt.Sprintf(`models:
  - key: %s
    provider: FAKE
    model_id: canned-cv
    display_name: Bad Key
`, tc.key))
			c, err := Load(path)
			if err == nil {
				t.Fatalf("Load accepted key %q, want charset error", tc.key)
			}
			if c != nil {
				t.Fatal("Load returned a catalog alongside an error")
			}
			if err.Error() != tc.wantErr {
				t.Errorf("error = %q, want %q", err, tc.wantErr)
			}
		})
	}
}

func TestLoadAcceptsValidKeyCharset(t *testing.T) {
	c, err := Load(loadInlineYAML(t, `models:
  - key: anthropic/claude-x
    provider: ANTHROPIC
    model_id: claude-x
    display_name: Claude X
  - key: a_b.c-d=e
    provider: OPENAI
    model_id: m
    display_name: M
`))
	if err != nil {
		t.Fatalf("Load rejected valid keys: %v", err)
	}
	kv := newFakeKV()
	if err := c.Seed(context.Background(), kv); err != nil {
		t.Fatalf("Seed: %v", err)
	}
	for _, want := range []string{"anthropic/claude-x", "a_b.c-d=e"} {
		found := false
		for _, p := range kv.puts {
			if p == want {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("key %q not seeded, puts = %v", want, kv.puts)
		}
	}
	if len(kv.deletes) != 0 {
		t.Errorf("deletes = %v, want none when bucket starts empty", kv.deletes)
	}
}
