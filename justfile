set shell := ["bash", "-cu"]

compose := "docker compose -f deploy/compose/compose.yaml"

default:
    @just --list

# Lint protos and regenerate Go + Python code
proto:
    buf lint
    buf generate

# Check proto backwards compatibility against main
proto-breaking:
    buf breaking --against '.git#branch=main'

# Start the core stack
up:
    {{compose}} up -d --build

# Start the core stack + observability profile (enables OTel export in services)
up-obs:
    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 {{compose}} --profile observability up -d --build

down:
    {{compose}} --profile observability down -v

logs *args:
    {{compose}} logs -f {{args}}

# Run goose migrations against the compose postgres
migrate:
    {{compose}} run --rm migrate

lint:
    buf lint
    uv run ruff check .
    uv run ruff format --check .
    uv run ty check
    cd services/gateway && go vet ./...

fmt:
    uv run ruff format .
    cd services/gateway && gofmt -w cmd internal

test: test-py test-go

test-py:
    uv run pytest

test-go:
    cd services/gateway && go test ./...

# End-to-end test against the compose stack using the fake model
e2e:
    ./scripts/e2e.sh

run-gateway:
    cd services/gateway && go run ./cmd/gateway

run-ai:
    uv run --package ai-processor ai-processor

run-render:
    uv run --package cv-generator cv-generator
