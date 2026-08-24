# 0004: CI golangci-lint failures (twice)

**Symptom.** All CI green except `go`.

**Cases.** (a) `errcheck` on `obj.Body.Close()` in a defer →
`defer func() { _ = obj.Body.Close() }()`. (b) `staticcheck` on a
deprecated valkey-go OTel constructor.

**Lesson.** Reproduce the CI lint locally with the exact pinned version
(`go run .../golangci-lint@v2.x`) before pushing; drift between local and
CI linters wastes round-trips.
