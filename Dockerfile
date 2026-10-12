# Whydunit engine (FastAPI). Built remotely (GitHub Actions / the host), never on the dev machine.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY engine ./engine
COPY simulator ./simulator
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
# Pre-generate every fixture world so the playground never builds one at request time on a small host.
RUN uv run --no-sync python -c "from engine.fixtures.world import resolve_world; from engine.settings import load_config; [resolve_world(n) for n in load_config('worlds')]"

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync whydunit db upgrade && uv run --no-sync uvicorn engine.api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
