// Package catalog loads the model catalog from YAML, seeds the NATS KV
// bucket, and serves in-memory lookups and fuzzy search for the UI.
package catalog

import (
	"context"
	"fmt"
	"os"
	"strings"

	natsjs "github.com/nats-io/nats.go/jetstream"
	"google.golang.org/protobuf/proto"
	"gopkg.in/yaml.v3"

	catalogv1 "github.com/corruptmane/cv/services/gateway/gen/cvgen/catalog/v1"
)

type yamlEntry struct {
	Key         string  `yaml:"key"`
	Provider    string  `yaml:"provider"`
	ModelID     string  `yaml:"model_id"`
	DisplayName string  `yaml:"display_name"`
	Description *string `yaml:"description"`
}

type yamlFile struct {
	Models []yamlEntry `yaml:"models"`
}

// Catalog is the in-memory model catalog, in YAML file order.
type Catalog struct {
	entries []*catalogv1.ModelCatalogEntry
	byKey   map[string]*catalogv1.ModelCatalogEntry
}

// Load reads and validates the catalog YAML file.
func Load(path string) (*Catalog, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read catalog: %w", err)
	}
	var f yamlFile
	if err := yaml.Unmarshal(raw, &f); err != nil {
		return nil, fmt.Errorf("parse catalog yaml: %w", err)
	}
	if len(f.Models) == 0 {
		return nil, fmt.Errorf("catalog %s contains no models", path)
	}

	c := &Catalog{byKey: make(map[string]*catalogv1.ModelCatalogEntry, len(f.Models))}
	for i, m := range f.Models {
		if m.Key == "" || m.ModelID == "" || m.DisplayName == "" {
			return nil, fmt.Errorf("catalog entry %d: key, model_id and display_name are required", i)
		}
		providerName := "PROVIDER_" + strings.ToUpper(m.Provider)
		providerNum, ok := catalogv1.Provider_value[providerName]
		if !ok || providerNum == int32(catalogv1.Provider_PROVIDER_UNSPECIFIED) {
			return nil, fmt.Errorf("catalog entry %q: unknown provider %q", m.Key, m.Provider)
		}
		if _, dup := c.byKey[m.Key]; dup {
			return nil, fmt.Errorf("catalog entry %q: duplicate key", m.Key)
		}
		entry := &catalogv1.ModelCatalogEntry{
			Key:         m.Key,
			Provider:    catalogv1.Provider(providerNum),
			ModelId:     m.ModelID,
			DisplayName: m.DisplayName,
			Description: m.Description,
		}
		c.entries = append(c.entries, entry)
		c.byKey[m.Key] = entry
	}
	return c, nil
}

// Seed upserts every catalog entry into the KV bucket as binary
// protobuf, keyed by catalog key.
func (c *Catalog) Seed(ctx context.Context, kv natsjs.KeyValue) error {
	for _, entry := range c.entries {
		data, err := proto.Marshal(entry)
		if err != nil {
			return fmt.Errorf("marshal catalog entry %q: %w", entry.GetKey(), err)
		}
		if _, err := kv.Put(ctx, entry.GetKey(), data); err != nil {
			return fmt.Errorf("seed catalog entry %q: %w", entry.GetKey(), err)
		}
	}
	return nil
}

// Get returns the entry for a key, or nil.
func (c *Catalog) Get(key string) *catalogv1.ModelCatalogEntry {
	return c.byKey[key]
}

// All returns every entry in catalog (YAML) order.
func (c *Catalog) All() []*catalogv1.ModelCatalogEntry {
	return c.entries
}

// Search returns entries whose key or display name matches the query
// as a case-insensitive subsequence, preserving catalog order. An
// empty query returns everything.
func (c *Catalog) Search(query string) []*catalogv1.ModelCatalogEntry {
	q := strings.ToLower(strings.TrimSpace(query))
	if q == "" {
		return c.entries
	}
	var out []*catalogv1.ModelCatalogEntry
	for _, entry := range c.entries {
		if isSubsequence(q, strings.ToLower(entry.GetKey())) ||
			isSubsequence(q, strings.ToLower(entry.GetDisplayName())) {
			out = append(out, entry)
		}
	}
	return out
}

// isSubsequence reports whether every rune of needle appears in
// haystack in order (not necessarily contiguously).
func isSubsequence(needle, haystack string) bool {
	if needle == "" {
		return true
	}
	n := []rune(needle)
	i := 0
	for _, r := range haystack {
		if r == n[i] {
			i++
			if i == len(n) {
				return true
			}
		}
	}
	return false
}
