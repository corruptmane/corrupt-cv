package modelcfg

import (
	"os"
	"path/filepath"
	"testing"
)

const sample = `
providers:
  test:
    - id: deterministic
      label: Deterministic
      default: true
  openai:
    - id: gpt-4o-mini
      label: GPT-4o mini
      default: true
    - id: gpt-4o
      label: GPT-4o
`

func load(t *testing.T) *Registry {
	t.Helper()
	path := filepath.Join(t.TempDir(), "models.yaml")
	if err := os.WriteFile(path, []byte(sample), 0o600); err != nil {
		t.Fatal(err)
	}
	reg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

func TestForAndValid(t *testing.T) {
	reg := load(t)
	if len(reg.For("openai")) != 2 {
		t.Errorf("openai should have 2 models")
	}
	if !reg.Valid("openai", "gpt-4o") {
		t.Errorf("gpt-4o should be valid for openai")
	}
	if reg.Valid("openai", "nope") {
		t.Errorf("unknown model should be invalid")
	}
	if reg.Valid("unknown-provider", "x") {
		t.Errorf("unknown provider should be invalid")
	}
}

func TestDefaultAndResolve(t *testing.T) {
	reg := load(t)
	if got := reg.Default("openai"); got != "gpt-4o-mini" {
		t.Errorf("default openai = %q, want gpt-4o-mini", got)
	}
	// invalid/empty -> default
	if got := reg.Resolve("openai", ""); got != "gpt-4o-mini" {
		t.Errorf("resolve empty = %q, want default", got)
	}
	if got := reg.Resolve("openai", "bogus"); got != "gpt-4o-mini" {
		t.Errorf("resolve invalid = %q, want default", got)
	}
	// valid -> unchanged
	if got := reg.Resolve("openai", "gpt-4o"); got != "gpt-4o" {
		t.Errorf("resolve valid = %q, want gpt-4o", got)
	}
}

func TestLoadErrors(t *testing.T) {
	if _, err := Load(filepath.Join(t.TempDir(), "missing.yaml")); err == nil {
		t.Errorf("missing file should error")
	}
}
