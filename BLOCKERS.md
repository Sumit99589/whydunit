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
| B2 | Make `Sumit99589/whydunit` **public** (Settings → General → Change visibility). The simulator runs ~400 Actions minutes/day; private repos get 2,000/month. The hackathon also requires a public repo. | open |
| B3 | Create an empty **public** repo `Sumit99589/acme-demo` (no README). Say so and the agent pushes `~/acme-demo` (main plus the incident branch `refactor/signup-idle-hydration`). Create a fine-grained token for **acme-demo only** with Contents, Pull requests, Actions = read/write; put it in `.env` as `ACME_GITHUB_TOKEN=`. | open |
| B4 | In Vercel, import `acme-demo` (production branch `main`). Set its env vars: `ACME_DATABASE_URL` (= Neon URL), `WHYDUNIT_ENGINE_URL` (from B11), `NEXT_PUBLIC_WHYDUNIT_KEY` (agent generates), `STRIPE_SECRET_KEY` (B7, optional at first). Put the production URL in `.env` as `ACME_URL=` and a token that can read its deployments as `VERCEL_TOKEN=` (plus `VERCEL_TEAM_ID=` if it is in a team). | open |
| B5 | Create a Neon Postgres project; put the pooled connection string (with `sslmode=require`) in `.env` as `DATABASE_URL=`. The agent runs the migrations. | open |
| B11 | Host the engine publicly (steps in `docs/hosting.md`). Recommended: a free **Hugging Face Docker Space** built from `hosting/hf-space/` (first make the GHCR package `whydunit-engine` public), with secrets `DATABASE_URL`, `WHYDUNIT_ADMIN_KEY` (any long random string), `NEBIUS_API_KEY`, `TAVILY_API_KEY`. Alternative: render.com Blueprint from `render.yaml` (sleeps when idle). Put the URL in `.env` as `WHYDUNIT_ENGINE_URL=` and in the repo variable `WHYDUNIT_ENGINE_URL`. | open |

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
