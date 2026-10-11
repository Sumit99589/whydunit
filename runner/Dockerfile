# Whydunit browser runner: Playwright (Chromium, WebKit, Firefox) + the engine package.
# Built in GitHub Actions (runner-image.yml) and pushed to GHCR; runs as a Nebius Serverless Job/Endpoint.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY engine ./engine
COPY simulator ./simulator
COPY runner ./runner
COPY config ./config
RUN uv sync --frozen --no-dev && \
    mkdir -p runner/static && \
    curl -fsSL -o runner/static/rrweb.umd.min.cjs https://cdn.jsdelivr.net/npm/rrweb@2.1.7/dist/rrweb.umd.min.cjs && \
    curl -fsSL -o runner/static/style.min.css https://cdn.jsdelivr.net/npm/rrweb@2.1.7/dist/style.min.css

ENV PATH="/opt/venv/bin:$PATH" PORT=8080
EXPOSE 8080
ENTRYPOINT ["python", "-m", "runner"]
CMD ["serve"]
