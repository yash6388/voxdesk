# One image for every backend service — API, MCP server and both A2A agents run the same
# code with a different command (see docker-compose.yml).
FROM python:3.13-slim

# Pin uv to the version used in development for reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first (cached layer): only re-installed when the lock file changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .
ENV PATH="/app/.venv/bin:$PATH"

# Run as an unprivileged user; data/models is a mounted volume for the voice models.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p data/models /home/app/.cache/huggingface \
    && chown -R app:app /app /home/app
USER app

EXPOSE 8000
CMD ["./scripts/docker_api.sh"]
