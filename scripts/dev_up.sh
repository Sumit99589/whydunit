#!/usr/bin/env bash
# One-command local setup: database, a project key, the fixture worlds and a first case. No external keys needed.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync
uv run whydunit db upgrade
uv run whydunit project create acme "Acme Notes" --key "${WHYDUNIT_INGEST_KEY:-wd_acme_devkey}" >/dev/null
for w in 3inc deploy_only ads_only payments_only holiday_red_herring noise outage competitor tracking seasonality seasonality_small_bug; do
  uv run whydunit world create --preset "$w" >/dev/null && echo "world $w ready"
done
uv run whydunit case open --world fixture:3inc | tail -3
echo
echo "Now run:  uv run whydunit serve        (engine on :8000)"
echo "and:      cd ui && pnpm install && pnpm dev   (case board on :3000)"
