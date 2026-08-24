package config

import (
	"testing"
)

func TestMaxBodyBytesDefault(t *testing.T) {
	t.Setenv("MAX_BODY_BYTES", "")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.MaxBodyBytes != 262144 {
		t.Fatalf("MaxBodyBytes default = %d, want 262144", cfg.MaxBodyBytes)
	}
}

func TestMaxBodyBytesOverride(t *testing.T) {
	t.Setenv("MAX_BODY_BYTES", "4096")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.MaxBodyBytes != 4096 {
		t.Fatalf("MaxBodyBytes = %d, want 4096", cfg.MaxBodyBytes)
	}
}

func TestCookieSecureDefault(t *testing.T) {
	t.Setenv("COOKIE_SECURE", "")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.CookieSecure {
		t.Fatal("CookieSecure default must be false")
	}
}

func TestInsecureSecretWarning(t *testing.T) {
	cases := []struct {
		name     string
		secret   string
		devMode  bool
		wantWarn bool
	}{
		{"default secret outside dev", DefaultSessionSecret, false, true},
		{"default secret in dev mode", DefaultSessionSecret, true, false},
		{"custom secret outside dev", "a-real-production-secret", false, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			warn, ok := Config{SessionSecret: tc.secret, DevMode: tc.devMode}.InsecureSecretWarning()
			if ok != tc.wantWarn {
				t.Fatalf("InsecureSecretWarning() ok = %v, want %v", ok, tc.wantWarn)
			}
			if ok && warn == "" {
				t.Fatal("warning text must not be empty")
			}
		})
	}
}
