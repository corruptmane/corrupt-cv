# Build context: repo root.
#   docker build -f services/ai-processor/Dockerfile .
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS build
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# uv workspaces need every member's pyproject.toml present to resolve, even
# when only one package is being synced. Full sources are only needed for the
# target service and the shared lib (workspace members install editable, so
# the venv points back into these directories).
COPY pyproject.toml uv.lock ./
COPY libs/python/ libs/python/
COPY services/ai-processor/ services/ai-processor/
COPY services/cv-generator/pyproject.toml services/cv-generator/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ai-processor

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
RUN useradd --uid 65532 --user-group --create-home app
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/libs /app/libs
COPY --from=build /app/services/ai-processor /app/services/ai-processor
USER app
EXPOSE 9090
ENTRYPOINT ["ai-processor"]
