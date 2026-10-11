# Hugging Face Docker Space for the Whydunit engine: reuses the image CI publishes to GHCR.
FROM ghcr.io/sumit99589/whydunit-engine:latest
# Spaces run as uid 1000; the engine writes its LLM cache and local blobs under /app/.cache.
USER root
RUN mkdir -p /app/.cache && chown -R 1000:1000 /app/.cache
USER 1000
ENV HOME=/tmp UV_CACHE_DIR=/tmp/uv-cache PORT=7860
EXPOSE 7860
