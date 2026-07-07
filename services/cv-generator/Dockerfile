# Multistage build (uv workspace). The `typst` PyPI package bundles the compiler,
# so no system Typst install is needed. Build stage syncs a non-editable venv at
# /venv; runtime is a slim python image with just that venv.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/venv
WORKDIR /w
COPY pyproject.toml uv.lock ./
COPY proto/gen/python ./proto/gen/python
COPY libs/cvworker ./libs/cvworker
COPY services/ai-processor/pyproject.toml ./services/ai-processor/pyproject.toml
COPY services/cv-generator ./services/cv-generator
RUN uv sync --frozen --no-dev --no-editable --package cv-generator

FROM python:3.13-slim-bookworm AS runtime
COPY --from=build /venv /venv
ENV PATH="/venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "cv_generator.main"]
