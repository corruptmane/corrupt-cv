# Build context: repo root.
#   docker build -f services/gateway/Dockerfile .
FROM golang:1.26 AS build
WORKDIR /src

# Module files first for layer caching.
COPY services/gateway/go.mod services/gateway/go.sum services/gateway/
RUN --mount=type=cache,target=/go/pkg/mod \
    cd services/gateway && go mod download

COPY services/gateway/ services/gateway/
WORKDIR /src/services/gateway
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/gateway ./cmd/gateway

# Distroless runtime: no shell, no package manager. This means the container
# CANNOT run a compose healthcheck command; orchestration relies on the
# gateway's own dependencies being healthy (depends_on) and on the ops server
# (:9090 /healthz, /readyz) for external probes. HTML templates and static
# assets are embedded in the binary via go:embed.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/gateway /usr/local/bin/gateway
# In-image default catalog; compose bind-mounts the repo copy over it so
# catalog edits do not require an image rebuild.
COPY configs/model-catalog.yaml /etc/cvgen/model-catalog.yaml
EXPOSE 8080 9090
ENTRYPOINT ["/usr/local/bin/gateway"]
