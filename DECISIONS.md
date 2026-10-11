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
