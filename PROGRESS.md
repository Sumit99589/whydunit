# Progress

Current stage: **Waiting on human prerequisites** (BLOCKERS.md). Every stage that can be built without
credentials is built and verified (Stages 4, 6, 7, 9, 10, 13, 15 done; 1–3, 5, 8, 11, 12, 14 built; 16 written).
Stage 17 starts only after the submission is drafted on Devpost (PLAN), which needs the human.

**When credentials arrive, in this order:**
1. ~~B2 + B3 + B4 + B5 + B11~~ done 2026-10-11: repos public, Acme on Vercel (https://acme-demo-lac.vercel.app),
   Neon migrated, engine on Render (https://whydunit-engine.onrender.com), Actions secrets set, simulator started.
   6 clean ticks confirmed 19:00Z; the simulator chains its own runs (D79).
2. B1 → `scripts/discover_models.py --write`, `scripts/smoke_llm.py`; rerun `whydunit evals run` in LLM mode.
3. B8 → Tavily cassettes; B7 → real Stripe declines; B6 + B9 → runner as a Nebius Serverless Job.
4. At T+5.5d the watcher should auto-open the flagship live case → Stage 11 live loop → set `FLAGSHIP_CASE_ID`.
5. ~~B12~~ UI live at https://whydunit-gamma.vercel.app (all live-shots checks pass, 2026-10-12); record the video (docs/video-script.md); submit (docs/devpost.md checklist).

Simulator start time: **2026-10-11T16:51:36Z** (T+4d = Oct 15 16:51 UTC deploy bug; flagship case ≈ Oct 17 04:51 UTC).
An earlier start at 14:47Z was discarded: a test run with real credentials merged the incident branch early; acme-demo
`main` was reset to `f26fcbc`, the bad Vercel deployment deleted, the Neon data wiped, and tests now strip real env.

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

## Stage 3 — Live world simulator ✅ (running since 2026-10-11T16:51:36Z)
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
- [x] Started 2026-10-11T16:51:36Z; first tick clean (5/5 probes, real sessions recorded through Acme → engine)
- [x] 6 consecutive clean ticks (17:45–19:00Z, 5/5 probes each; replays stored in Postgres). One earlier tick (17:42Z)
      timed out on a sleeping Render engine; ticks now wake it first. Runs chain every ~5.5 h (D79).

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

## Stage 10 — The case board UI ✅ (ui-smoke green in CI: 1440/390 px × light/dark, live + replay)
- [x] Design system: cool paper/slate, evidence-marker yellow, Schibsted Grotesk, numbered evidence tents
- [x] `/` landing (pitch, looping case preview, how a case runs, what is real); `/cases`; `/cases/[id]` board:
      header with drop and status track, metric chart with cause markers, roster of seven, findings + evidence wall
      (click a finding to light its evidence), interrogation thread, blame waterfall with CI whiskers, verdict,
      how we know, not checked, fix and verify panel; replay at 1×/4×/16×; `/playground`; `/connect`; `/evals`
- [x] `ui-smoke.yml`: Chromium at 1440/390 px × light/dark, no overflow, no console errors, live + replay runs

## Stage 11 — Fix, verify, close, watch (built; live "done when" waits on B2–B7, B9, B11)
- [x] `engine/agents/fixer.py`: code PRs (Super forward fix, revert fallback) verified on Vercel preview across the
      browser matrix with up to 2 revisions; approval-gated merge, ad budget restore, payments mitigation
- [x] `engine/runtime/verify.py`: per-cause recovery vs baseline, close or reopen
- [x] `engine/runtime/watcher.py` + `watcher.yml`: sustained-drop detection, auto-opened case, fixes, webhook
- [x] API: approve/verify endpoints (admin key); CLI `whydunit watch`, `whydunit fix approve`
- [x] Tests: fixture fixes are proposals only; verification closes after real recovery and not before; watcher
      opens a case on a sustained drop and ignores noise (`tests/test_fix_verify.py`)
- [ ] Live: watcher auto-opens, three causes, PR verified and merged, budget restored, metric recovers, case closes

## Stage 12 — The rest of the ladder (built; live screen-reading run needs a runner + B1 for Omni)
- [x] Tier 2: `Warehouse` (generic SQL via `config/warehouse.yaml`), `PyAirbyte` (Stripe charges, optional group)
- [x] Tier 3: `CSVUpload` with Nano/rule column mapping, editable preview, confirm (admin key)
- [x] Tier 4: `ScreenReader` (runner `capture` job → Omni, or rendered table text) on the simulated ad dashboard
- [x] Tier 6: evidence requests on the case board with an upload link
- [x] `/connect`: ladder per kind with the active tier, test-connection buttons, CSV upload panel
- [x] Done when (tests): with the ads API off, the Ads detective finds the $450 → $150 cut by screen reading at
      confidence ≤ 0.6; a Stripe-style CSV export is mapped by rules and used as the tier-3 payments source
      (`tests/test_ladder.py`, 5 tests incl. the Omni path with a scripted vision backend)

## Stage 13 — Evaluation harness ✅ (deterministic mode; LLM-mode rerun waits on B1)
- [x] `engine/evals/run.py`, `uv run whydunit evals run`: ten scenarios S1–S10, results in
      `engine/evals/results.json`, table in README, `/evals` page (`GET /evals`)
- [x] Metrics: top-cause accuracy, share MAE, false-accusation rate, correct abstention, missed causes, time, cost
- [x] Result: top cause 10/10, false accusations 0, share MAE 0.17 pp, abstention 2/2, ~2.5 s per case, $0
- [x] Failures analysed in DECISIONS D69

## Stage 14 — Hosting for judges (built; deploys wait on B4, B5, B11, B12)
- [x] Hosting plan and steps (`docs/hosting.md`); Nebius endpoint cost computed (D70); HF Space files; `render.yaml`
- [x] Judge modes: replay (`/cases/flagship`), playground (real Nemotron + one real Tavily call), live Acme (read-only)
- [x] Guards: per-IP cases/hour, daily global budget with a replay fallback banner; per-case budget cap
- [x] `/status` endpoint; `uptime.yml` daily check that opens an issue; simulator `traffic.scale`
- [ ] Deployed: fresh browser, no credentials, replays the flagship and runs a playground case on the public URL;
      cost per playground case measured (needs B1 for a non-zero number)

## Stage 15 — Hardening and revisits ✅ (credential-bound revisits remain: D21, D28, D69)
- [x] Snippet recorder lazy-loaded (6 KB core); UI error states; detective fallback notes on the roster
- [x] Rate limits on public endpoints; approval gates; no secrets to the client; checked uploads
- [x] Performance: fixture cases ~2.5 s end to end; the live flagship should take well under 4 min, to be measured on B1
- [x] README run instructions + `scripts/dev_up.sh`

## Stage 16 — Submission package (written; recording and submitting need the human)
- [x] `docs/architecture.md` + README diagram; `docs/video-script.md` (2:45); `docs/devpost.md` with feedback, testing
      instructions and the checklist
- [ ] Demo URL, video, Devpost submission (B10, B12)

## Last verification
```
uv run pytest -q              → 81 passed
uv run ruff check .           → clean
snippet: pnpm test/typecheck  → 10 passed, clean
acme-demo: tsc + eslint       → clean
local tick (--skip-browsers)  → 19 visitors, 4 signups, 1 paid, 49 events ingested in-process
```
