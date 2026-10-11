# Hosting for judges (Stage 14)

| Piece | Where | Why |
|---|---|---|
| UI (`ui/`) | Vercel project, root directory `ui` | Free, preview deployments, edge compression |
| Engine (`Dockerfile`) | Hugging Face Docker Space (free CPU, 2 vCPU / 16 GB); Render free web service as the alternative (`render.yaml`) | Always-on hosting for 7 weeks on a Nebius Serverless Endpoint would cost ~$118 at ~$0.10/h for 4 vCPU / 16 GB, more than the ~$50 of credits (DECISIONS D70) |
| Database | Neon Postgres | Free, serverless |
| Browser runner | Nebius Serverless **Jobs** (per run), GitHub Actions fallback | Pay per job; keeps the project "running on Nebius" |
| Models | Nebius Token Factory (Nemotron) | Required runtime call |
| Simulator, watcher, uptime | GitHub Actions cron | Free for public repos |

## Steps

1. **Engine image**: CI publishes `ghcr.io/sumit99589/whydunit-engine:latest`. In GitHub → Packages → whydunit-engine
   → Package settings, make it **public** so the Space can pull it.
2. **Space**: create a Docker Space and push `hosting/hf-space/` (Dockerfile + README) to it. In the Space settings,
   add secrets: `DATABASE_URL`, `NEBIUS_API_KEY`, `TAVILY_API_KEY`, `WHYDUNIT_ADMIN_KEY`, `CORS_ORIGINS` (the UI URL),
   `FLAGSHIP_CASE_ID` (after Stage 11), and the S3 variables. The engine URL is `https://<user>-<space>.hf.space`.
3. **UI**: import the repo in Vercel with root directory `ui`; set `WHYDUNIT_ENGINE_URL` to the engine URL.
4. **Repo variables** (Settings → Variables): `WHYDUNIT_UI_URL`, `WHYDUNIT_ENGINE_URL` for the uptime check.
5. **Seed the public database**: `uv run whydunit db upgrade` and `uv run whydunit evals run` against it, so the evals
   table links to cases that exist; set `FLAGSHIP_CASE_ID` to the live flagship case once Stage 11 has produced it.
6. After the video is recorded, set `traffic.scale: 0.3` and `traffic.real_sessions_per_tick: [0, 1]` in
   `config/incidents.yaml` to run the simulator at a low steady rate.

## Judge modes and guards

- **Replay** (`/cases/flagship?replay=4`): zero cost, always available.
- **Playground** (`/playground`): fixture worlds with real Nemotron calls and a real Tavily search. Each IP may open
  3 cases an hour, and new cases stop when the day's model spend reaches $2 (`config/budgets.yaml`); the UI then
  points to the replay. Each case also has its own budget cap.
- **Live Acme**: investigates the running sandbox read-only; fixes are shown, never applied (approvals need
  `WHYDUNIT_ADMIN_KEY`).
- No login anywhere.
