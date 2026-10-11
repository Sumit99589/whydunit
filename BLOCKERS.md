# Blockers — things only the human can do

Each item names the exact ask. Work continues against mocks with the same interface until it lands.
Put secrets in `/home/sumit/whydunit/.env` (copy `.env.example`); never paste them in chat or commits.

| # | Needed for | Exact ask | Status |
|---|---|---|---|
| B1 | Every model call (Stage 1 "done when") | Create a Nebius Token Factory API key, redeem `NEBIUS-DEVPOST-GLOBAL26`, join the Builders Program, and set `NEBIUS_API_KEY=` in `.env`. If the dashboard shows a regional base URL, also set `NEBIUS_BASE_URL=`. Then run `uv run python scripts/discover_models.py --write && uv run python scripts/smoke_llm.py`. | open |
| B2 | Simulator on GitHub Actions (Stage 3), judging rule | Make `Sumit99589/whydunit` **public** (Settings → General → Danger zone → Change visibility). It is private today; the hackathon requires a public repo, and a 10-minute simulator cron on a private repo would exhaust the free Actions minutes in about a week. | open |
| B3 | Acme sandbox (Stage 2) | Create an empty **public** repo `Sumit99589/acme-demo` (no README). The code is built locally in `~/acme-demo` and will be pushed there. Also create a fine-grained token scoped to `acme-demo` with Contents, Pull requests and Actions = read/write, and set `GITHUB_TOKEN=` in `.env`. | open |
| B4 | Acme hosting (Stage 2), Deploy detective | In Vercel, import `acme-demo` as a project (production branch `main`), and create a Vercel API token that can read its deployments: set `VERCEL_TOKEN=` (and `VERCEL_TEAM_ID=` if it lives in a team). Later the Whydunit UI needs a second project from `whydunit` with root directory `ui`. | open |
| B5 | Production DB | Create a Neon Postgres project and set `DATABASE_URL=` (the pooled connection string with `sslmode=require`). Local dev uses an embedded Postgres until then. | open |
| B6 | Replays, screenshots | Create an S3-compatible bucket (Nebius Object Storage preferred) and set `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`. Local dev writes blobs to `.cache/blobs` until then. | open |
| B7 | Payments | Stripe account in **test mode**: set `STRIPE_SECRET_KEY` (sk_test_…), `STRIPE_PUBLISHABLE_KEY` (pk_test_…). The webhook secret can come later. | open |
| B8 | World and Voice detectives, Tavily bonus | Set `TAVILY_API_KEY=` (the Builders Program includes Tavily credits). | open |
| B9 | Runner as Nebius Serverless Job (Stage 8) | Create a Nebius AI Cloud project, install the `nebius` CLI and run `nebius profile create`, then set `NEBIUS_PROJECT_ID=`. Confirm a Serverless Job can pull a public GHCR image. | open |
| B10 | Submission | Register on Devpost and join the hackathon; have a YouTube channel ready for the video. | open |
