# syntax=docker/dockerfile:1.7

# ---- Builder stage: resolve + install dependencies with uv ----
FROM python:3.12-slim AS builder

# Install uv (fast pip-compatible resolver) via the official installer image
COPY --from=ghcr.io/astral-sh/uv:0.4.20 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_PREFERENCE=only-system \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy only the dependency manifest first so this layer caches when only
# source code changes.
COPY pyproject.toml ./
COPY README.md ./README.md
# Lockfile is optional (may not exist on first build). `|| true` keeps it from
# breaking an initial build without uv.lock present.
COPY uv.lock* ./

# Install deps into a project-local .venv.
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# Copy source
COPY app ./app
COPY jobs ./jobs
COPY main.py ./main.py
COPY words.csv ./words.csv


# ---- Runtime stage: minimal image, non-root user ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Create a non-root user to actually run the service as
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

# Copy .venv + source from builder
COPY --from=builder --chown=app:app /app /app

# Logs directory — mounted at /app/logs in k8s if a PVC is wanted
RUN mkdir -p /app/logs && chown -R app:app /app/logs

USER app

# Long-running service: APScheduler lives inside main.py. Override with
# `python -m jobs.import_words` or `python -m jobs.send_daily_word` for
# manual one-shots via `kubectl exec`.
CMD ["python", "main.py"]
