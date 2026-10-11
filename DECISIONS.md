# Decisions

Non-obvious choices and why. Items marked **revisit** are simplifications to come back to in Stage 15.

## Stage 1

- **D1. No AI attribution in commits.** PLAN A7.5 forbids it; the plan is the user's own instruction and
  overrides tool defaults.
- **D2. Single `pyproject.toml` at the repo root** builds the `engine` and `simulator` packages, so
  `uv run whydunit …` works from the root as the plan's CLI examples assume.
- **D3. Local dev Postgres = `pgserver`** (a pip package bundling real Postgres binaries). The machine has
  only the Postgres client and no server, and installing one needs root. Production uses Neon via
  `DATABASE_URL`; the same Alembic migrations run on both.
- **D4. LLM cache is a content-addressed disk cache** (`.cache/llm`, sha256 of the full request including
  model, messages, tools and the reasoning flag). Cache hits are recorded with zero cost so per-case cost
  reflects real spend.
- **D5. Reasoning switch** is sent as `extra_body.chat_template_kwargs.enable_thinking` (the vLLM /
  Nemotron 3 convention). A `system_flag` mode (`/think`, `/no_think`) is configurable in
  `config/models.yaml` in case Token Factory ignores the kwarg.
- **D6. Model IDs are unverified** until a Token Factory key exists (BLOCKERS B1). Ultra and Omni IDs and
  prices come from third-party catalogs that list Nebius-hosted models; `discover_models.py --write`
  replaces them from `GET /v1/models` and flips `verified: true`.
- **D7. Role fallbacks** (`ultra → super`) live in config and in `LLM.resolve_role`, per risk register C3.
- **D8. Docker is actually installed on this machine**, but PLAN A4/A7.6 say images are built in GitHub
  Actions. Following the plan: no local image builds (memory).

## Stage 2

- **D9. Acme proxies snippet uploads** through its own `/api/wd/*` route on Vercel. Events then arrive
  first-party (no CORS, fewer ad-blocker losses) and the proxy forwards Vercel's `x-vercel-ip-country` as
  `x-whydunit-country`. Simulator traffic keeps its simulated country (the GitHub runner is in the US).
- **D10. Stripe stays test-mode by construction**: Acme refuses to start with a non-test key. Without a
  key, checkout uses a mock with the same interface and the same outcome for each test PaymentMethod, and
  every attempt is recorded in `acme.payment_attempts` either way.
- **D11. Acme's tables live in an `acme` schema** in the shared Postgres, created by Whydunit's first
  migration and mirrored in `acme-demo/db/schema.sql` (idempotent), so either repo can bootstrap them.
- **D12. Snippet bundle is 80 KB minified** because rrweb's recorder is bundled in. Acceptable for a demo;
  revisit lazy-loading the recorder only for sampled sessions (**revisit**).

## Stage 3

- **D13. The simulated ad platform is branded "AdPilot"** in its dashboard, with a "SIMULATED" banner,
  and its API is Google-Ads-shaped. No Google trademarks appear in UI or video.
- **D14. One world model** (`engine/world/model.py`) drives both the live simulator and the fixture
  worlds, so the two never disagree about funnel rates or segment mix.
- **D15. Planted code bug = `requestIdleCallback` with no fallback.** CI probe on 2026-10-11
  (`browser-features` workflow): `requestIdleCallback` is `undefined` in Playwright WebKit 26.6 (desktop
  and iPhone 15) and a function in Chromium 153 (desktop and Pixel 7) and Firefox 155. The refactor
  (branch `refactor/signup-idle-hydration` in acme-demo) only enables submit once an idle callback fires,
  so on WebKit the Create account button silently does nothing: dead clicks, then rage clicks. Every iOS
  browser is WebKit, so iPhone Chrome users are hit too.
- **D16. Incident messages are emergent**: support tickets and reviews about the incidents come from a
  share of the visitors whose signup was actually blocked or whose card was actually declined, not from a
  script.

## Stage 4

- **D17. Common random numbers.** Every visitor draws a fixed vector of uniforms, arrivals are drawn at
  1.6× the base rate and thinned, and ad clicks and CPCs are drawn before the budget is applied. So the
  same seed with any subset of incidents switched off is the *exact* counterfactual world. Ground-truth
  shares are exact Shapley values of lost paid subscriptions over those 2^k worlds, computed per day
  (per-day seeds) over the case window only. The 3-incident world, including its 8 counterfactuals,
  generates in about 7 s.
- **D18. Case baseline is week-over-week by default** (the same weekdays one week earlier), the standard
  growth-analytics comparison that removes the weekly cycle. The seasonality scenarios use the preceding
  weekdays instead, on purpose, to test that Whydunit recognises a weekend dip.
- **D19. Payment-declines incident tuned to 3% → 30% for Brazil, with Brazil at 15% of traffic** (the plan
  said "about 18%"). At 18% the true share was 1.6% of the drop, too small to be a meaningful cause. Now
  the flagship's true shares are about 65% Safari bug, 29% ads cap, 6% Brazil declines. The same values
  are used by the live simulator.
- **D20. Fixture news and status incidents are clearly fictional** (example.com sources, a fictional
  competitor "Quillboard"), so fixtures never invent claims about real companies. Holidays are real
  (Nager.Date 2026, plus India's three national holidays added by hand because Nager.Date lacks India).
- **D21. Fixture session recordings are synthesised rrweb streams** of the signup page (valid snapshots,
  inputs, clicks, navigations; blocked users show repeated clicks with no DOM change). Live recordings come
  from real browsers. Fixture flow results are recorded per deployment until the three permanent Acme
  deployments exist (B4), when `config/fixture_deployments.yaml` gets their URLs and flows run for real
  (**revisit**).
- **D22. pytest temp dirs live in `.cache/pytest`**: `/tmp` is RAM-backed here and fixture worlds are
  ~10 MB each.

## Stage 5

- **D23. Each kind has a fixed column schema** (`KIND_SCHEMAS`); `make_bundle` rejects a connector that
  omits a column. Detectives and analysis therefore never care which tier supplied the data.
- **D24. Tier confidence weights**: API 1.0, warehouse 0.95, CSV 0.85, public web 0.7, screen reading 0.6,
  human upload 0.8. The lead multiplies finding confidence by these.
- **D25. Registry falls down the ladder on errors too**, not just on unavailability, and records each
  step in the bundle's `notes`. When nothing can supply a kind it raises `NoSource` listing what was
  tried; detectives turn that into `cannot_determine` and the verdict's "not checked" list.
- **D26. Acme's `payment_attempts` table is a tier-2 source for `payments`**, so the Payments detective
  still works before Stripe is connected (and in no-key local runs). It is honestly labelled tier 2.
- **D27. Acme's checkout charges a PaymentIntent for the first month**, then starts the subscription from
  the saved card. Charging through a confirmed PaymentIntent records decline codes on the intent and its
  charge (attaching a decline card first can fail before any charge exists). Stripe API version in use:
  `2026-09-30.endive` (field `allowed_payment_method_types`).
- **D28. Tests mock HTTP with respx and fake SDK clients instead of vcrpy cassettes for now**, because
  cassettes need real keys. Recording real cassettes for Tavily, Stripe, Vercel and GitHub happens as keys
  arrive (B1, B3, B4, B7, B8), for the Stage 13 eval harness (**revisit**).
- **D29. Neon is not on Atlassian Statuspage** (neonstatus.com runs on status.io), so it is listed with
  no status feed and reported under "not checked" instead of being silently skipped.
- **D30. All DB and DuckDB sessions use UTC**, so evidence timestamps never depend on the machine's zone.

## Stage 6

- **D31. Monotone funnel.** A session that reached a later step counts as having reached the earlier
  ones, so the decomposition is always well defined. Raw event flags are kept beside it so a tracking
  gap (downstream events without upstream ones) can still be detected as a measurement problem.
- **D32. Decomposition is LMDI** (log-mean Divisia): contributions add up exactly to the total change
  (checked to 1e-12 in tests), per day so baseline and window lengths can differ.
- **D33. Segment mix effects are measured against the overall average rate**: (Δw)·(r̄_s − r̄). The naive
  symmetric form (Δw)·r̄_s made any segment whose share moved look important (the US outranked Brazil on
  payment success in the flagship). The terms still sum exactly to the factor's change.
- **D34. Attribution = counterfactual restoration on an hourly grid + exact Shapley + parametric
  bootstrap.** With nothing restored the model reproduces the actual window exactly. Downstream rates are
  shrunk toward segment and window-wide pooled rates *only* where an upstream factor is restored. Without
  that, tiny cells' noisy rates were multiplied by restored volumes and the Safari bug was overstated by
  17 pp. Restored traffic is the baseline's same hours scaled by the unaffected traffic trend. Result on
  the flagship: 68.2 / 22.6 / 9.2 % vs exact truth 68.7 / 21.8 / 9.5 %.
- **D35. Ad demand gets the same day-level market noise as organic traffic** (world model). The traffic
  trend adjustment assumes channels share market-level swings; the world now does too.
- **D36. Brazil decline incident raised to 45% (from a 3% baseline) and, in fixtures, starts the afternoon
  of the Safari-bug day.** At 18% or 30% the true share was 2–4% of the drop, below what CUSUM can time at
  ~2 Brazilian checkouts per hour. At 45% it is ~9.5%: a real, smaller, third cause. The live simulator
  uses the same rate. Supersedes D19's numbers.
- **D37. "Real drop vs normal variance"** compares the window with the same weekdays in prior weeks and
  an overdispersed Poisson variance estimated from history (|z| ≥ 2.5 and ≥ 5% change). A weekend dip
  against preceding weekdays is therefore reported as seasonal.

## Stage 7

- **D38. Playbook first, model second.** Each detective runs a deterministic playbook (the standard checks,
  computed by code, pinning evidence and metrics), so a case always produces validated findings, even with
  no Token Factory key, a model outage or an exhausted budget. When a key is present, Nano extends the
  investigation through tools and Super writes the final report; if any model step fails, the playbook's
  findings stand. Reports record `model_mode` so the UI can say which happened.
- **D39. Analysis results are evidence too**: every computed table (decomposition, segment breakdown,
  change timing) is pinned as an `analysis:*` bundle that names its source evidence and inherits the
  weakest source tier. Findings cite both the raw source and the analysis.
- **D40. The validator strips non-claims before matching numbers**: dates, times, ids, shas, versions,
  device names such as "iPhone 15". Every other number must match a referenced metric within rounding
  (half a unit in the last shown digit plus 1%). Rates may be written as percentages. Inference findings
  get an extra ×0.85 on confidence.
- **D41. SSE polls the event table** (0.4 s) instead of an in-process pub/sub, so streaming works across
  processes and hosts (the engine may run several workers). Replay re-emits stored events with their
  original gaps, capped at 4 s and divided by the requested speed.

## Stage 8

- **D42. Runner backends in preference order: Nebius Serverless Job → GitHub Actions → local (dev) →
  recorded fixture results.** Jobs write `runs/<job_id>/results.json` (and screenshots or keyframes) to
  object storage, and the engine polls for that file. Nebius's docs don't name a job-status command
  (FEEDBACK), and polling storage works the same for every backend. Without a bucket, the Actions backend
  uploads an artifact that the engine downloads. Nebius CPU platform and preset are in
  `config/runner.yaml`, unverified until B9.
- **D43. One signup flow implementation** (`runner/flows.py`) serves the Deploy detective, the
  simulator's health probes, and the runner image. The flow also records whether `/api/signup` was ever
  requested and whether anything covers the button, so the failure mode is evidence ("the button press
  never sends the request").
- **D44. Keyframes come from rrweb's own Replayer** (rrweb 2.1.7 UMD, vendored into the runner image at
  build time, CDN fallback), paused at each click, every 4 s, and at the end.
- **D45. Deploy suspect-line heuristics** use a table of engine-specific APIs (requestIdleCallback,
  scheduler.postTask, navigator.userAgentData, …) matched against *added* diff lines and checked against
  exactly which engines fail. Super refines this when a model is available. Fixture worlds have no
  renderer, so the Session detective reports heuristics only there and Omni runs only on live recordings.
- **D46. Voice topics**: Nano classifies messages into a fixed topic list in batches of 25, with keyword
  rules as the fallback; spikes use a Poisson surprise with a floor, so a topic that was silent in the
  baseline can still register. Quoted customer text (“…”) is exempt from number validation: it is
  evidence, not a claim.
- **D47. The World detective always ends with an explicit checked-list** (searches run, results reviewed,
  holiday countries, status pages, and anything it could not check). Relevance of news is judged by Nano,
  falling back to event-word rules within the window.
- **D48. Evidence is keyed by (case_id, id)** (migration 0003). Evidence ids are deterministic hashes of
  the query, so two cases on the same world produce the same ids.
- **D49. The Funnel detective runs its tracking-integrity check on every case**, and tests the case's own
  metric (`signups` uses raw signup_completed events). A tracking bug can look like "no real drop" in paid
  subscriptions while signups appear to collapse.

## Stage 9

- **D50. Hypotheses carry their evidence by role.** Proposals from the detective that owns a mechanism
  (deploy, ads, payments, world) contribute *mechanism* evidence and name the cause (their segment and
  time win when merged). Funnel break points that line up within 4 h contribute *timing* evidence.
  Proposals merge when factor, segment and start agree (different dimensions with the same start, such
  as os=iOS and engine=webkit, also merge).
- **D51. Cross-examination is structured.** Questions have a `kind` (before_after, deploy_around,
  ads_change_around, payments_segment, external_release, external_event) answered by code that pins new
  evidence. Round 1 always re-confirms timing at the mechanism's exact moment and asks the World detective
  to rule out a browser release for engine-specific signup drops. Later rounds only fill gaps. Answers
  are supports, contradicts, neutral or cannot_determine, and contradictions are kept in the thread.
- **D52. Judgement is code**: supported ⇔ mechanism ∧ timing ∧ no contradiction; anything else is
  inconclusive or rejected, with the reason stored. Only supported hypotheses are attributed, so a
  harmless deploy (flows pass) can never be blamed.
- **D53. Special verdicts read the Funnel detective's structured state** (change verdict, tracking-gap
  finding), not finding text, so they still work when Super rewrites the findings in LLM mode.
- **D54. Ultra only rewrites the verdict narrative** (one call per case) and the number validator checks
  it. If any number is not a computed metric, the template narrative stands and a `narrative_rejected`
  event is logged. Shares are displayed within 0–100% (CI bounds clipped).

## Stage 10

- **D55. Visual direction: a case board, keyed to crime-scene evidence markers.** Cool paper (#F1F4F8) or
  slate (#121820) with one accent, evidence-marker yellow (#F2C12E), used for the numbered tents that
  mark pinned evidence (numbered in pin order, a real sequence) and for highlights. One family (Schibsted
  Grotesk) with tabular figures only where numbers line up. No all-caps eyebrows, no mono labels, no
  card-kit gradients. The one orchestrated motion is the blame waterfall drawing in, cause by cause, when
  the verdict lands. Other motion only answers state changes: a pulsing dot on a working detective, and
  markers dropping onto the wall. Reduced motion is respected.
- **D56. The board is client-rendered from the event log** through a `/engine/*` rewrite to the engine,
  using the same reducer for live, history and replay, so replay is pixel-identical to the live run.
  Next 16's Cache Components shell stays static and the case streams in.
- **D57. `compress: false` in the UI and `no-transform` on SSE**: the live stream never ends, so gzip in
  `next start` held back its tail (the first CI smoke run caught a live case that never updated).
  Vercel compresses at its edge anyway.
- **D58. UI checks run in GitHub Actions** (`ui-smoke.yml`): Postgres service, engine, `next build` +
  `next start`, Chromium at 1440 px and 390 px in light and dark, checks for overflow and console errors,
  live and replay runs, and screenshots as an artifact. Locally, available memory was under the 3 GB
  floor from ~/.claude/CLAUDE.md for the whole session.

## Stage 11

- **D59. Code fixes go through the GitHub contents API, not a local clone**: the engine container has no
  git, and a single-file fix needs only "read file at ref, write file on a branch, open PR". Super writes the
  forward fix (whole file). The deterministic fallback restores the file as it was before the culprit
  commit, i.e. a revert.
- **D60. Nothing is applied without approval**, and approval needs `WHYDUNIT_ADMIN_KEY`. That covers
  merging a PR, changing an ad budget, and switching on the payments mitigation. On the public demo
  judges see fixes and their verification but cannot change anything. Fixture worlds produce proposals
  only. Live investigations opened through the API do not open PRs; only the watcher (or an admin) does.
- **D61. Verification = each cause's factor, in its segment, back above the 90% Wilson lower bound of its
  baseline rate** (traffic causes use the segment's share of visitors, robust to the daily curve), after a
  30-minute settle and a minimum sample. All causes recovered → case closed. Not recovered 24 h after the
  fix → case reopened with the reason.
- **D62. The watcher waits for a sustained drop** (≥ 15% and z ≤ −3 against the same hours one and two
  weeks earlier, at now, now − 18 h and now − 36 h) before opening a case. One bad afternoon is not a case.
  In the live world this also means the auto-opened case covers all three planted incidents
  (T+4d to T+5d).

## Stage 12

- **D63. Per-kind availability in the registry** (`available_for(kind)`, not cached): a CSV upload makes the
  tier-3 connector a source only for its own kind, and can arrive mid-case.
- **D64. CSV mapping = Nano first, rules second.** Synonym lists (Stripe's export headers among them) plus
  fuzzy matching. Values are normalised per kind: dollars → cents, Stripe statuses → succeeded or
  requires_payment_method, outcome derived from the decline reason. The user sees and can edit the
  mapping before it becomes a source. Activating an upload needs the admin key, so a judge's upload cannot
  quietly change the live world's evidence for everyone.
- **D65. Screen reading reads the dashboard's tables from section screenshots with Omni, falling back to
  the rendered table text when no vision model is available** (labelled as such in the bundle). The
  runner gained a `capture` job: full-page and per-section screenshots, plus each table's text. Bundles are
  tier 4: confidence ×0.6, a "screen-read, medium confidence" note, and the screenshot as the audit artifact.
  The Ads detective matches campaigns by name (screen-read rows have no ids), uses the dashboard's "limited
  from HH:00" hour, and says the figures are approximate.
- **D66. PyAirbyte is wired for one real source (Stripe charges → payments) as an optional dependency
  group.** It installs each connector into its own virtualenv, too heavy for the default install and the
  engine image. Adding a source is a dict entry in `engine/connectors/airbyte_conn.py`. Locking the group
  downgraded wrapt to 1.17.3; all tests still pass.
- **D67. Tier 6 (ask a human) is an `evidence_requests` row plus a card on the case board** linking to the
  upload panel pre-filled with the kind and case. The case never waits for it.

## Stage 13

- **D68. Scoring.** A named cause matches a planted incident when it has the same funnel factor and the
  incident's segment (a global incident matches any narrowing). Top cause = the cause with the largest
  share vs the incident with the largest true Shapley share, or the right special verdict for
  abstention scenarios. Share error compares `share_of_explained` with the exact truth, and only when
  the incident really cost ≥ 3 paid subscriptions (otherwise a share is undefined).
- **D69. Failure analysis.**
  1. The first holiday scenario (German Unity Day, Germany at 10% of traffic) cost 0 paid subscriptions
     in truth: a one-day dip in one mid-size country is below the noise. The verdict still credited the
     holiday, with a 100 pp share error. The scenario is now US Labor Day (36% of traffic; truly costs
     19 of 98 paid subs that day), still with a harmless deploy the same morning.
  2. A first fix made any within-variance headline a "no real drop" verdict, which turned five
     single-cause scenarios into misses (5/10). Real but small causes are real: the verdict now names
     them and adds a caveat that the overall change is within normal variance.
  3. Cached fixture worlds did not notice preset changes. Worlds now store a spec hash and regenerate
     when it differs.
  Final: top cause 10/10, 0 false accusations, share MAE 0.17 pp, abstentions 2/2 (deterministic
  mode). LLM-mode results will be added once B1 lands (**revisit**).

## Stage 14

- **D70. The engine is not hosted on a Nebius Serverless Endpoint.** A 4 vCPU / 16 GB CPU instance is about
  $0.10/h (Nebius price list, "from $0.10/h" for CPU-only Genoa; ~$71/month for cpu-d3 4 vCPU / 16 GB on
  getdeploying.com). Always-on until Dec 15 (~7 weeks, ~1,180 h) would be ~$118, more than all the
  credits (~$50). Recommended host: a free Hugging Face Docker Space (2 vCPU / 16 GB; the daily uptime ping
  keeps it awake), Render as the alternative. Nebius Serverless **Jobs** stay for the browser runner,
  paid per run, and Token Factory serves every model call.
- **D71. Public-demo guards live in the engine** (`POST /cases`): 3 new cases per IP per hour and a $2
  daily model budget for non-watcher cases. When either trips, the API returns 429 with a fallback link
  and the playground shows "watch the solved case". Each case still has its own $0.60 cap. Admin-key
  requests bypass the guards. Live Acme investigations are read-only.
- **D72. The playground makes one real Tavily call per case** (the Voice detective's public-chatter
  search) when a key is configured. Everything else in a fixture world stays deterministic, so eval
  results and the playground agree.
- **D73. The simulator has a `traffic.scale` knob** to turn the world down after recording the video.

## Stage 15

- **D74. Revisits.** D12 done: the snippet core is 6 KB and the 75 KB rrweb recorder loads only for sampled
  sessions (`whydunit-record.js`). Still open, because they need credentials: D21 (permanent Acme deployments
  for fixture flows), D28 (real HTTP cassettes) and D69 (LLM-mode eval run).
- **D75. Error states.** The case board explains a missing case, an unreachable engine (with links to the
  case list and the replay), a stopped investigation (findings so far stay visible), and metric history
  that could not load. The roster shows when a detective fell back to computed findings (model unavailable
  or over budget), and detective crashes show as errors without sinking the case.
- **D76. Public endpoints are rate-limited per IP**: new cases 3/h, CSV uploads 5/h with a 5 MB cap,
  connection tests 10/h. Admin-key requests are exempt. All writes that change the world need the admin
  key. Secrets never reach the client: `/status` reports only booleans and model IDs.
- **D77. Engine on Render free, blobs in Postgres.** Hugging Face now charges for Docker Spaces (PRO), so
  the engine runs on Render's free plan from the public GHCR image. Render's disk is wiped on sleep and
  redeploy, so without an S3 bucket blobs go to a `blobs` table in Neon (about 15 KB per recorded session,
  roughly 80 MB over the run). GitHub's `*/15` cron is heavily throttled on this repo (one scheduled run in
  2.5 h on day one); ticks catch up on missed windows, so lost ticks cost real-browser sessions, not traffic.
- **D78. Tests never see real credentials.** `tests/conftest.py` strips every real-system variable that
  `.env` provides. A run before this change used the real acme-demo token and merged the planted incident
  branch four days early; the clock was restarted after resetting `main` and wiping Neon.
