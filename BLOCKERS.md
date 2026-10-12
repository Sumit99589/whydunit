# Blockers — things only the human can do

Each item names the exact ask. Work continues against mocks with the same interface until it lands.
Put secrets in `/home/sumit/whydunit/.env` (copy `.env.example`); never paste them in chat or commits.
Once values are in `.env`, the agent can copy them into GitHub Actions secrets with `gh secret set`.

## ⏱ Critical path: start the live simulator (needs ~7 days of history before the video)

The simulator is built and tested (`simulator/`, `.github/workflows/simulator.yml`). It idles until these
exist. Incidents fire at T+4d, T+4.5d and T+5d, so **every day of delay here pushes the flagship recording
back a day** (deadline Oct 30).

| # | Exact ask | Status |
|---|---|---|
| B2 | ~~Make `Sumit99589/whydunit` public~~ — done by the agent 2026-10-11 after a history scan for secrets found none. | done |
| B3 | ~~Create public repo `Sumit99589/acme-demo`~~ — done by the agent 2026-10-11 (main and `refactor/signup-idle-hydration` pushed). **Still needed:** a fine-grained token for **acme-demo only** with Contents, Pull requests, Actions = read/write, in `.env` as `ACME_GITHUB_TOKEN=` (GitHub has no API to create one). | token open |
| B4 | ~~Import acme-demo into Vercel~~ — done 2026-10-11: production `https://acme-demo-lac.vercel.app`, env `ACME_DATABASE_URL`, `NEXT_PUBLIC_WHYDUNIT_KEY`, `WHYDUNIT_ENGINE_URL` set; deployment protection turned off by the human. | done |
| B5 | ~~Neon Postgres~~ — done by the agent 2026-10-11: project `whydunit` (`billowing-dust-33887443`, aws-us-east-1), migrated to 0004, Acme project registered; `DATABASE_URL` in `.env` and in Actions secrets. | done |
| B11 | ~~Host the engine~~ — done by the agent 2026-10-11 on Render free (`https://whydunit-engine.onrender.com`, image `ghcr.io/sumit99589/whydunit-engine:latest`, Virginia). HF Spaces needed PRO. Add `NEBIUS_API_KEY` / `TAVILY_API_KEY` to the Render service when B1/B8 land (the agent can do it from `.env`). | done |

## Everything else

| # | Needed for | Exact ask | Status |
|---|---|---|---|
| B1 | Every model call (Stage 1 "done when") | Create a Nebius Token Factory API key, redeem `NEBIUS-DEVPOST-GLOBAL26`, join the Builders Program, and set `NEBIUS_API_KEY=` in `.env`. If the dashboard shows a regional base URL, also set `NEBIUS_BASE_URL=`. The agent then runs `scripts/discover_models.py --write` and `scripts/smoke_llm.py`. | open |
| B6 | Replays, screenshots | Create an S3-compatible bucket (Nebius Object Storage preferred) and set `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` in `.env` (and on the engine host). Until then blobs live in Postgres (`blobs` table, migration 0005), about 15 KB per recorded session, so this is optional. | open |
| B7 | Real Stripe declines | Stripe account in **test mode**: `STRIPE_SECRET_KEY` (sk_test_…) on Acme's Vercel project and in `.env`. Without it, Acme's checkout uses a mock with identical outcomes. | open |
| B8 | World and Voice detectives, Tavily bonus | Set `TAVILY_API_KEY=` in `.env` (the Builders Program includes Tavily credits). | open |
| B9 | Runner as Nebius Serverless Job (Stage 8) | Create a Nebius AI Cloud project, install the `nebius` CLI and run `nebius profile create`, then set `NEBIUS_PROJECT_ID=`. Confirm a Serverless Job can pull a public GHCR image. | open |
| B12 | Judge demo | ~~Import this repo into Vercel~~ — done by the agent 2026-10-12: project `whydunit` (root `ui`), `https://whydunit-gamma.vercel.app`, builds only when `ui/` changes; repo variable `WHYDUNIT_UI_URL` set. `live-shots` workflow verifies it end to end. | done |
| B10 | Submission | Register on Devpost and join the hackathon; have a YouTube channel ready for the video. | open |
