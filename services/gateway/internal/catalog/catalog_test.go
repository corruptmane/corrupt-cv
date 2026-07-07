package catalog

import (
	"os"
	"path/filepath"
	"testing"

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
