# Build context is the repo root (see docker-compose.yml) so the proto/gen/go module
# referenced via the go.mod replace directive is available. Builds both the gateway
# and the one-shot migrate binary; the migrate compose service overrides the entrypoint.
FROM golang:1.26 AS build
WORKDIR /src
COPY proto/gen/go ./proto/gen/go
COPY services/gateway ./services/gateway
WORKDIR /src/services/gateway
ENV CGO_ENABLED=0 GOWORK=off
RUN go build -trimpath -ldflags="-s -w" -o /out/gateway ./cmd/gateway && \
    go build -trimpath -ldflags="-s -w" -o /out/migrate ./cmd/migrate

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/gateway /gateway
COPY --from=build /out/migrate /migrate
# Baked default model registry; compose mounts the repo copy over it for live edits.
COPY config/models.yaml /config/models.yaml
ENV MODELS_CONFIG_PATH=/config/models.yaml
EXPOSE 8080 9090
ENTRYPOINT ["/gateway"]
