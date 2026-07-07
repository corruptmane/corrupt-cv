# CV generator — task runner. `just` to list recipes.
set shell := ["bash", "-uc"]

default:
    @just --list

# ---- contracts / codegen ----

# Regenerate protobuf stubs (Go + Python) and tidy the Go contracts module.
generate:
    cd proto && buf generate
    cd proto/gen/go && go mod tidy

# Lint protos.
proto-lint:
    cd proto && buf lint

# CI parity: lint, check breaking vs main, regenerate, fail on any diff.
proto-check:
    cd proto && buf lint
    cd proto && buf format --diff --exit-code
    cd proto && buf generate
    git diff --exit-code -- proto/gen || (echo "generated code is stale: run 'just generate'" && exit 1)

# ---- local stack ----

# Build and start the whole stack.
up:
    docker compose up -d --build

# Stop and remove the stack + volumes.
down:
    docker compose down -v

# Tail logs (optionally: just logs gateway).
logs *svc:
    docker compose logs -f {{svc}}

ps:
    docker compose ps

# Validate compose without a running daemon.
compose-check:
    docker compose config -q && echo "compose OK"

# ---- per-service dev ----

gateway-build:
    cd services/gateway && go build ./...

gateway-test:
    cd services/gateway && go test ./...

gateway-lint:
    cd services/gateway && go vet ./...

ai-sync:
    cd services/ai-processor && uv sync

ai-test:
    cd services/ai-processor && uv run pytest -q

cvgen-sync:
    cd services/cv-generator && uv sync

cvgen-test:
    cd services/cv-generator && uv run pytest -q

# ---- aggregate ----

# Run all unit tests (Go + both Python services).
test: gateway-test ai-test cvgen-test

# Lint everything.
lint: proto-lint gateway-lint
    cd services/ai-processor && uv run ruff check . && uv run ty check
    cd services/cv-generator && uv run ruff check . && uv run ty check

# Format everything.
fmt:
    cd proto && buf format -w
    cd services/gateway && gofmt -w .
    cd services/ai-processor && uv run ruff format .
    cd services/cv-generator && uv run ruff format .

# End-to-end smoke against the running stack using the deterministic TestModel
# (no API key). Submits a generation and polls until a PDF is downloadable.
smoke:
    ./scripts/smoke.sh
