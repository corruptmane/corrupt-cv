// Package web embeds the gateway's HTML templates and static assets so the
// binary is self-contained.
package web

import "embed"

//go:embed templates/*.html static/*
var FS embed.FS
