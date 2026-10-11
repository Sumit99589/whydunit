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
| B4 | ~~Import acme-demo into Vercel~~ — done by the agent 2026-10-11: project `acme-demo`, production `https://acme-demo-lac.vercel.app`, env `ACME_DATABASE_URL` and `NEXT_PUBLIC_WHYDUNIT_KEY` set. **Still needed:** previews sit behind Vercel Deployment Protection, which blocks the browser runner on fix previews: in Vercel → acme-demo → Settings → Deployment Protection, turn off Vercel Authentication (Acme is a public sandbox) or create a Protection Bypass for Automation secret. `WHYDUNIT_ENGINE_URL` waits on B11. | protection open |
| B5 | ~~Neon Postgres~~ — done by the agent 2026-10-11: project `whydunit` (`billowing-dust-33887443`, aws-us-east-1), migrated to 0004, Acme project registered; `DATABASE_URL` in `.env` and in Actions secrets. | done |
| B11 | Host the engine publicly. **Hugging Face now requires PRO ($9/month) for Docker Spaces** (the free create call returns 402). Choose one: (a) subscribe to HF PRO and the agent deploys the Space with the existing `HF_TOKEN`; (b) create a free render.com account and put an API key in `.env` as `RENDER_API_KEY=` (the agent creates the service from the public GHCR image; it sleeps when idle). Until then the simulator ingests in-process, and only real-browser snippet events through Acme's `/api/wd` proxy are lost. | open |

## Everything else

| # | Needed for | Exact ask | Status |
|---|---|---|---|
| B1 | Every model call (Stage 1 "done when") | Create a Nebius Token Factory API key, redeem `NEBIUS-DEVPOST-GLOBAL26`, join the Builders Program, and set `NEBIUS_API_KEY=` in `.env`. If the dashboard shows a regional base URL, also set `NEBIUS_BASE_URL=`. The agent then runs `scripts/discover_models.py --write` and `scripts/smoke_llm.py`. | open |
| B6 | Replays, screenshots | Create an S3-compatible bucket (Nebius Object Storage preferred) and set `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` in `.env` (and on the engine host). Local dev writes blobs to `.cache/blobs` until then. | open |
| B7 | Real Stripe declines | Stripe account in **test mode**: `STRIPE_SECRET_KEY` (sk_test_…) on Acme's Vercel project and in `.env`. Without it, Acme's checkout uses a mock with identical outcomes. | open |
| B8 | World and Voice detectives, Tavily bonus | Set `TAVILY_API_KEY=` in `.env` (the Builders Program includes Tavily credits). | open |
| B9 | Runner as Nebius Serverless Job (Stage 8) | Create a Nebius AI Cloud project, install the `nebius` CLI and run `nebius profile create`, then set `NEBIUS_PROJECT_ID=`. Confirm a Serverless Job can pull a public GHCR image. | open |
| B12 | Judge demo | Import this repo into Vercel with root directory `ui` and env `WHYDUNIT_ENGINE_URL`; set the repo variable `WHYDUNIT_UI_URL` to the resulting URL (uptime check). | open |
| B10 | Submission | Register on Devpost and join the hackathon; have a YouTube channel ready for the video. | open |
