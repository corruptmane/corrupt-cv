// Package modelcfg loads the configurable provider->model registry (YAML) so the
// selectable models can change without a code change (edit the file + restart).
package modelcfg

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

type Model struct {
	ID      string `yaml:"id"`
	Label   string `yaml:"label"`
	Default bool   `yaml:"default"`
}

type Registry struct {
	providers map[string][]Model
}

type fileShape struct {
	Providers map[string][]Model `yaml:"providers"`
}

func Load(path string) (*Registry, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read models config: %w", err)
	}
	var f fileShape
	if err := yaml.Unmarshal(data, &f); err != nil {
		return nil, fmt.Errorf("parse models config: %w", err)
	}
	if len(f.Providers) == 0 {
		return nil, fmt.Errorf("models config %q has no providers", path)
	}
	return &Registry{providers: f.Providers}, nil
}

// For returns the models offered for a provider (nil if unknown).
func (r *Registry) For(provider string) []Model { return r.providers[provider] }

// Valid reports whether id is an offered model for provider.
func (r *Registry) Valid(provider, id string) bool {
	for _, m := range r.providers[provider] {
		if m.ID == id {
			return true
		}
	}
	return false
}

// Default returns the provider's default model id (the one flagged default, else
// the first, else "").
func (r *Registry) Default(provider string) string {
	models := r.providers[provider]
	for _, m := range models {
		if m.Default {
			return m.ID
		}
	}
	if len(models) > 0 {
		return models[0].ID
	}
	return ""
}

// Resolve returns id if valid for provider, otherwise the provider default.
func (r *Registry) Resolve(provider, id string) string {
	if r.Valid(provider, id) {
		return id
	}
	return r.Default(provider)
}
