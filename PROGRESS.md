# Progress

Current stage: **Stage 10 — The case board UI** (Stages 1–3, 5 and 8 built, with their remaining "done
when" checks waiting on credentials in BLOCKERS.md per rule A7.3; Stages 4, 6, 7 and 9 done).

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
      68.7%, ads cap 21.8%, BR declines 9.5%
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

## Stage 6 — Analysis toolkit ✅
- [x] `config/metrics.yaml`; `analysis/data.py` (session funnel table, derived `engine` dimension)
- [x] `decompose.py`: LMDI funnel decomposition, exact to 1e-12
- [x] `segments.py`: mix/rate drill-down per factor, two levels deep
- [x] `changepoint.py`: seasonally matched real-vs-noise test; CUSUM change timing
- [x] `shapley.py`: counterfactual restoration, exact Shapley, bootstrap CIs, unexplained share
- [x] `sessions.py`: rage clicks, dead clicks, form abandonment, keyframe times; `bootstrap.py` helpers
- [x] Done when: flagship shares within ±5 pp of truth (68.2/22.6/9.2 vs 68.7/21.8/9.5); factors and
      segments recovered; noise and weekend dip judged "within normal variance"; CUSUM times all three
      incidents within 1 h (`tests/test_analysis.py`, 12 tests)

## Stage 7 — Agent runtime and the first detective ✅ (LLM path verified with a scripted backend; real Nemotron waits on B1)
- [x] Schemas: Case, Finding, Hypothesis + EffectSpec, DetectiveReport, Question/Answer, MetricRef
- [x] Detective loop: playbook → Nano tool loop → Super JSON report → validator (one re-prompt, then suspicion)
- [x] Validator: evidence must exist in the case; numbers must match referenced metrics; tier-scaled confidence
- [x] Case event log in `case_events`, SSE `GET /cases/{id}/stream` (live and `?replay=1&speed=4`), cases API
- [x] Funnel detective; CLI `uv run whydunit case open --world fixture:3inc --metric paid_subs`
- [x] Done when: on fixture:3inc it reports the real drop, "signup rate fell, concentrated in WebKit (Safari and
      every iOS browser) 9.5% → 0.9% from Thu 09:00", "paid traffic 900 → 596/day from Thu 21:00", and
      "payment success concentrated in Brazil 95.3% → 64.5%"; all evidence valid; events in DB; SSE read with curl

## Stage 8 — The remaining six detectives (fixture ✅; live checks wait on B1, B3, B4, B6, B9)
- [x] Runner package (`runner/`): signup flow across 5-browser matrix, rrweb keyframe rendering, `run-flows` /
      `render-replay` / `serve`; Dockerfile (Playwright 1.63 base); `runner-image.yml` (GHCR + smoke) and
      `runner-job.yml` (Actions fallback, hardened inputs)
- [x] `engine/runtime/runner_client.py`: Nebius Serverless Job / GitHub Actions / local / fixture backends
- [x] Deploy: flows on each deployment, first failing deploy, diff, engine-API suspect lines, Omni on the screenshot
- [x] Session: failed-signup recordings in the hardest-hit segment + controls; rage/dead clicks; Omni on keyframes
- [x] Payments: success, issuer vs Acme-side, segment decline spike with codes and start time; API-error outages
- [x] Ads: budget change history, budget-limited days and cap hour, clicks before/after
- [x] Voice: topic clustering (Nano or rules), spikes vs baseline, quotes, Tavily public chatter
- [x] World: Tavily news (competitors, industry, dependency outages), holidays, status pages, explicit checked-list
- [x] All seven run concurrently (`engine/agents/team.py`); `tests/test_detectives.py` (6 worlds)
- [ ] Live: Deploy detective finds the culprit through a real Nebius Job; Session Omni describes the failed taps

## Stage 9 — Lead detective ✅ (deterministic; Ultra narrative path waits on B1)
- [x] Opening brief: merge proposals into hypotheses with effect specs, mechanism vs timing evidence
- [x] Cross-examination ≤ 3 rounds with structured questions answered by detectives with new evidence
- [x] Code judgement (mechanism ∧ timing ∧ no contradiction); Shapley attribution with CIs + unexplained
- [x] Verdict: ranked causes, how we know, rejected/inconclusive, not checked, actions (code PR, approval-gated
      config, recommendation); special verdicts "no real drop" and "measurement problem"; Ultra narrative validated
- [x] Done when: flagship names all three causes, explained shares 68.3/22.6/9.1 vs truth 68.7/21.8/9.5, no
      false accusations; noise and weekend dip → no real drop; tracking bug → measurement; holiday red herring
      → only the holiday (`tests/test_lead.py`)

## Last verification
```
uv run pytest -q              → 71 passed
uv run ruff check .           → clean
snippet: pnpm test/typecheck  → 10 passed, clean
acme-demo: tsc + eslint       → clean
local tick (--skip-browsers)  → 19 visitors, 4 signups, 1 paid, 49 events ingested in-process
```
