package telemetry

import (
	"context"
	"errors"
	"log/slog"
)

// fanoutHandler dispatches every record to all wrapped handlers, so
// container logs (stderr JSON) and the OTel log bridge both see the
// same stream.
type fanoutHandler struct {
	handlers []slog.Handler
}

// NewFanoutHandler returns an slog.Handler that writes each record to
// every handler that reports itself enabled for the record's level.
func NewFanoutHandler(handlers ...slog.Handler) slog.Handler {
	return &fanoutHandler{handlers: handlers}
}

func (f *fanoutHandler) Enabled(ctx context.Context, level slog.Level) bool {
	for _, h := range f.handlers {
		if h.Enabled(ctx, level) {
			return true
		}
	}
	return false
}

func (f *fanoutHandler) Handle(ctx context.Context, r slog.Record) error {
	var errs []error
	for _, h := range f.handlers {
		if !h.Enabled(ctx, r.Level) {
			continue
		}
		errs = append(errs, h.Handle(ctx, r.Clone()))
	}
	return errors.Join(errs...)
}

func (f *fanoutHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	next := make([]slog.Handler, len(f.handlers))
	for i, h := range f.handlers {
		next[i] = h.WithAttrs(attrs)
	}
	return &fanoutHandler{handlers: next}
}

func (f *fanoutHandler) WithGroup(name string) slog.Handler {
	next := make([]slog.Handler, len(f.handlers))
	for i, h := range f.handlers {
		next[i] = h.WithGroup(name)
	}
	return &fanoutHandler{handlers: next}
}
