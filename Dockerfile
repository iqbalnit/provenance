FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra gcp --no-install-project
COPY provenance ./provenance
COPY console ./console
COPY demo ./demo
RUN uv sync --frozen --no-dev --extra gcp
# Cloud Run sets $PORT. Agent turns are long; the request timeout is raised at deploy time.
CMD ["sh", "-c", "uv run --no-sync uvicorn provenance.service.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
