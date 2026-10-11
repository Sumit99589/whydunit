# Progress

Current stage: **Stage 6 — Analysis toolkit** (Stages 1–3 and 5 built, with their remaining "done when"
checks waiting on credentials in BLOCKERS.md per rule A7.3; Stage 4 done).

Simulator start time: **not started** (waiting on BLOCKERS critical path: B2, B3, B4, B5, B11).

## Stage 1 — Repo scaffold, model client, smoke tests
- [x] Monorepo layout; `engine/runtime/llm.py` (roles, reasoning switch, retries, cache, cost meter, budgets)
- [x] `scripts/discover_models.py`, `scripts/smoke_llm.py`; unit tests with a fake backend
- [x] Next.js UI scaffold; CI (ruff, format, pytest, UI typecheck and lint, snippet) — **green on GitHub**
- [ ] Smoke script against Token Factory, model IDs verified — waiting on `NEBIUS_API_KEY` (B1)

## Stage 2 — Acme sandbox, snippet, ingest
- [x] DB schema (Alembic 0001): engine tables plus Acme's `acme` schema; embedded Postgres for dev/tests
- [x] Ingest API: `POST /ingest/events` (batched, idempotent, sessions upserted, geo-header country) and
      `POST /ingest/replay` (gzip chunks to blob storage + metadata row); project keys; rate limiting
- [x] Blob store: S3-compatible or local
- [x] `packages/snippet`: page views, track/identify, UA/attribution context, batching, beacon on hide,
      sampled rrweb recording in chunks; 10 unit tests; 80 KB IIFE build
- [x] `~/acme-demo` (local repo): landing, pricing, signup, onboarding, Stripe test-mode checkout (mock
      fallback), help form → helpdesk table, cookie banner, `/api/health`, `/api/wd/*` snippet proxy
- [ ] Push acme-demo, deploy on Vercel (B3, B4)
- [ ] **Done-when check** (real browser visit to production Acme → events + replay in DB and blob store,
      Stripe test subscription, helpdesk row) — after B3/B4/B5/B11 (and B7 for real Stripe)

## Stage 3 — Live world simulator
- [x] Shared world model (`engine/world/model.py`) used by simulator and fixtures
- [x] Simulated ad platform "AdPilot" (`engine/mock_ads/`): budget-capped delivery, Google-Ads-shaped
      reports and change events, no-API mode, HTML dashboard, migration 0002
- [x] `config/incidents.yaml`: deploy bug T+4d, ads budget cap T+4.5d, BR payment declines T+5d→T+9d
- [x] Incident branch `refactor/signup-idle-hydration` in acme-demo (requestIdleCallback, no fallback;
      verified in CI that Playwright WebKit 26.6 lacks the API and Chromium/Firefox have it — DECISIONS D15)
- [x] `simulator/tick.py`: incidents, browser-matrix health probes, ads, journeys through Acme's real API,
      real ingest, emergent tickets and reviews (Nano or templates), real recorded Playwright sessions,
      ground truth (`simulator/ground_truth.json`, committed by the workflow when it changes)
- [x] `.github/workflows/simulator.yml` every 15 min; idles until secrets exist
- [x] Engine container (`Dockerfile`, GHCR workflow, `render.yaml`)
- [ ] **Start it** (B2, B3, B4, B5, B11) and confirm 6 consecutive clean ticks

## Stage 4 — Fixture worlds ✅
- [x] `engine/fixtures/world.py`: DuckDB worlds with events, sessions, users, payments (Stripe-shaped),
      synthetic rrweb replays, deployments with diffs and per-browser flow results, ads (campaigns, hourly,
      change events), tickets, reviews, news, real holidays, status incidents, and `meta` ground truth
- [x] Incident library (`engine/fixtures/incidents.py`): deploy_bug(engine), ads_budget_cap,
      payment_declines(country), public_holiday(country), dependency_outage(service), competitor_launch,
      tracking_bug, seasonality_only, noise_only, harmless_deploy, checkout_slow
- [x] Exact Shapley ground truth over counterfactual worlds (common random numbers) — 3inc: Safari bug
      65.4%, ads cap 28.8%, BR declines 5.8% of 146 lost paid subs
- [x] Presets in `config/worlds.yaml` (one per eval scenario); CLI `uv run whydunit world create`
- [x] Done when: every preset generates in < 30 s (3inc with truth: ~7 s); `tests/test_world.py` asserts
      each incident's signal (10 tests)

## Stage 5 — Evidence layer and connectors
- [x] `engine/connectors/base.py`: Connector protocol, `EvidenceBundle` (id, kind, connector, tier,
      query, window, data_ref, summary, artifacts, fetched_at, sample, notes, frame), per-kind schemas, tier
      confidence; `registry.py` resolves best available per kind, falls down the ladder on errors, `NoSource`
- [x] Tier 1: WhydunitEvents, Replays (+ `recording()`), Vercel, GitHub (+ `compare()`, `pulls()`),
      Stripe (test-mode only), MockAds (in-process or HTTP; respects no-API mode), Helpdesk, Reviews,
      Tavily (+ `extract()`), Holidays (Nager.Date + bundled India), StatusPages; GoogleAds documented stub;
      tier 2 AcmePaymentLog
- [x] Fixture mode: `FixtureWorld` serves every kind plus `compare`, `flow_results`, `recording`
- [x] `tests/test_connectors.py` (12 tests, HTTP mocked); `scripts/evidence_probe.py`
- [x] Probe on fixture:3inc → 11/11 kinds; probe on live (dev DB) → 9/11 (deploys: needs VERCEL_TOKEN or
      GITHUB_TOKEN; world_news: needs TAVILY_API_KEY), with real GitHub and Vercel status-page incidents
- [ ] Live probe 11/11 once B3/B4/B8 land

## Last verification
```
uv run pytest -q              → 42 passed
uv run ruff check .           → clean
snippet: pnpm test/typecheck  → 10 passed, clean
acme-demo: tsc + eslint       → clean
local tick (--skip-browsers)  → 19 visitors, 4 signups, 1 paid, 49 events ingested in-process
```
