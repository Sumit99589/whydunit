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
