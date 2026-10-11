# Whydunit — Build Plan

> "Signups fell 23% since Tuesday. A founder normally loses days digging through eight dashboards.
> Whydunit sends a team of AI detectives and comes back in minutes with the answer, the proof, the fix,
> and confirmation that the fix worked."

This file is the complete, self-contained plan. It is written to be executed by Claude Code working
autonomously, stage by stage, in order. Read all of Part A before writing any code.

---

## PART A — Context and operating rules

### A1. The hackathon (hard facts)

| Item | Fact |
|---|---|
| Event | Nebius x NVIDIA Global AI Hackathon (Devpost: nebiusglobalaihackathon.devpost.com) |
| Deadline | **Fri Oct 30 2026, 10:00 AM PDT (10:30 PM IST)**. Judging runs Dec 1–15. |
| Must have | (1) A runtime call to the **Nebius Token Factory** inference API, or running on Nebius AI Cloud (Serverless Jobs, Serverless Endpoints, DevPods). (2) At least one **NVIDIA open model** (Nemotron). We do both. |
| Our track | **Best Apps and Agents** ("any app or agent someone would actually use… a workflow that runs itself… Nemotron 3 Ultra for serious reasoning, Nano or Super for fast everyday calls"). |
| Bonus we target | **Best Use of Tavily, $3,000**: needs a functional runtime call to the Tavily API. Our World detective makes one. |
| Prize rule | Each project can win one Overall Award, or one Track Award plus one Bonus Award. |
| Judging Stage 1 | Pass/fail: it fits the track and genuinely uses the required APIs. |
| Judging Stage 2 | Four **equal** criteria: **Technological Implementation**, **Design** ("a complete, coherent product experience, not just a technical proof of concept"), **Potential Impact** ("a credible, specific case for a real problem for a real audience… based on what's demonstrated"), and **Quality of the Idea** ("a creative, non-obvious use of the models… genuine understanding of the problem space"). |
| Repo | Public on GitHub, with an **open-source license detectable in the About section** (use MIT). The repo must contain everything needed to run the project. |
| Demo | A working URL, **free and unrestricted for judges until Dec 15**. If the site needs a login, put the credentials in the testing instructions. |
| Video | **Under 3 minutes**, public on YouTube, no copyrighted music or third-party trademarks. Judges may judge on the video and text alone. |
| Submission text | Must explain how Nemotron and Token Factory were used, plus any other Nebius tools. It also needs a **feedback section** on Nebius and NVIDIA tools, which qualifies for the "Most Valuable Feedback" award. |

### A2. What we are building (one paragraph)

Whydunit is an investigation engine for "why did this metric change?". A user (founder, PM, growth
lead) opens a **case** on a metric drop. Seven specialist **detective agents** investigate in parallel,
each using its own tools and data sources. A **lead detective** questions them, throws out any claim
without evidence, and **splits the blame between causes using maths, not vibes**. Whydunit then
**proposes or opens fixes**: a pull request for a code bug, an approval-gated change for an ads budget.
It **verifies** each fix by re-running the failing flow and watching the metric recover, and only then
closes the case. An always-on watcher can open cases by itself when it detects an anomaly.

### A3. Differentiators — never water these down

1. **It works across business tools**: deploys, product analytics, session recordings, ads, payments,
   support, and the outside world. Analytics tools explain changes only within their own data, and
   AI incident tools (Resolve, Traversal, Cleric) look only at infrastructure.
2. **No proof, no finding.** Every claim must cite evidence that the system actually fetched or
   produced. Code (not the model) validates this.
3. **Numbers come from code; language comes from models.** Detection, decomposition and attribution
   are deterministic statistics (log decomposition plus Shapley attribution, with bootstrap
   confidence intervals). Models choose what to investigate, interpret the results and write the
   narrative. Any number in the narrative must match a computed number.
4. **It closes the loop**: fix, then verify, then watch the metric recover, then close the case.
5. **It is honest about uncertainty**: an "unexplained" share, an "I cannot rule this out" when a
   source is missing, and the ability to say "this is a measurement bug, not a real drop".
6. **The connector ladder** (A5) means it keeps working when a tool has no API: a detective can
   read a dashboard screenshot with Nemotron Nano Omni.

### A4. Fixed tech decisions (do not re-litigate)

| Layer | Choice |
|---|---|
| Engine | Python 3.12, `uv` for environments, FastAPI + uvicorn, pydantic v2, httpx, the `openai` SDK pointed at Token Factory, duckdb + polars for analysis, psycopg 3, `playwright` (Python), `tavily-python`, `stripe`, boto3 (S3-compatible storage), pytest, vcrpy (HTTP cassettes for deterministic evals) |
| UI | Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + motion (Framer Motion), deployed on Vercel. Live updates via Server-Sent Events from the engine. |
| Sandbox startup "Acme" | A separate repo and a separate Vercel project, built with Next.js + TypeScript. Includes the Whydunit snippet. Stripe in **test mode**. |
| Snippet | A tiny TypeScript library (`packages/snippet`) that sends funnel events and records sessions with **rrweb** (sampled). It uploads to the engine's ingest API. |
| Database | Postgres (Neon free tier) in production. The analysis layer reads into duckdb/polars. Fixture worlds can also live in local duckdb files. |
| Blob storage | An S3-compatible bucket (Nebius Object Storage preferred; Cloudflare R2 or Vercel Blob as fallback) for rrweb recordings, screenshots and diffs |
| Heavy jobs | A browser "runner" container (Playwright with Chromium, WebKit and Firefox) running as a **Nebius Serverless Job**. It also works as an HTTP endpoint (a Nebius Serverless Endpoint) during demo windows. Images are built in **GitHub Actions** and pushed to GHCR, because Docker is not installed on the dev machine. |
| Agent runtime | A small asyncio orchestrator of our own with OpenAI-style tool calling, so there is no heavy framework to fight. |
| Licence | MIT, in both repos |

### A5. The connector ladder (core architecture idea)

Detectives never call vendors directly. They ask for evidence **by kind** (`deploys`, `funnel_events`,
`sessions`, `ad_performance`, `ad_changes`, `payments`, `support_tickets`, `reviews`, `world_news`,
`holidays`, `dependency_status`). A registry picks the best available connector for each kind:

1. **Official API or MCP**, e.g. GitHub, Vercel, Stripe, Tavily, status pages
2. **Warehouse or PyAirbyte**: the company's own warehouse, or PyAirbyte's open-source connectors for the long tail
3. **CSV export** uploaded by the user, with columns mapped by Nemotron Nano
4. **Screen reading**: a read-only browser agent screenshots the vendor's dashboard and **Nemotron Nano Omni** extracts the numbers. This evidence is lower confidence.
5. **Public web** via Tavily
6. **Ask the human**: the case shows a "Detective requests evidence: …" card with an upload button

Every piece of evidence records its tier, and the lead detective weighs confidence by tier. When a kind
has no source at all, the detective reports `cannot_determine` and the verdict lists it under "not checked".

### A6. Model usage (NVIDIA Nemotron on Token Factory)

| Model | Role |
|---|---|
| **Nemotron 3 Nano** (30B-A3B) | Detectives' routine tool-calling loops, ticket clustering, CSV column mapping, generating synthetic tickets and reviews for the simulator. Cheap and fast. |
| **Nemotron 3 Super** (120B-A12B) | Detective reasoning and final detective reports, reading code diffs, writing fix patches |
| **Nemotron 3 Ultra** | The lead detective only: cross-examination, hypothesis judgement, verdict narrative |
| **Nemotron 3 Nano Omni** | Vision. Keyframes from session replays, screenshots from browser flow runs, and dashboard screenshots in the screen-reading fallback. Assume **image input only**: one public listing shows the Nebius-hosted Omni as image-only, so turn video into keyframes. If video input turns out to work, add it as an enhancement. |

Token Factory facts to **verify at Stage 1** (do not trust these blindly):
- The base URL is `https://api.tokenfactory.nebius.com/v1/`. Some Nebius examples use a regional
  `https://api.tokenfactory.us-central1.nebius.com/v1/`. Use whichever the account's dashboard shows.
- The API is OpenAI-compatible, with the key sent as a Bearer token. Use the env var `NEBIUS_API_KEY`.
- Candidate model IDs seen in Nebius material: `nvidia/nvidia-nemotron-3-nano-30b-a3b` and
  `nvidia/nemotron-3-super-120b-a12b`. Ultra and Omni IDs are unknown, so **call `GET /v1/models`, pick
  the IDs, and pin them in `config/models.yaml`**. Never hard-code them anywhere else.
- Nemotron reasoning can usually be switched on and off. Find out how, via `chat_template_kwargs` or a
  system-prompt flag, from the model card or a test call. Use reasoning ON for Ultra and Super
  judgement calls and OFF for Nano tool loops.

### A7. Operating rules for the building agent (Claude Code)

1. **Work through Part B stages in order.** Do not start a stage until the previous stage's
   "Done when" checks pass. Exception: Stage 3's live simulator must be **started early and left
   running**, because it needs about 7 days of real history before the demo video is recorded.
2. **Keep these files in the repo root up to date:**
   - `PROGRESS.md`: the current stage, which steps are done, what's next, and the last verification output
   - `DECISIONS.md`: every non-obvious choice, with its reason
   - `BLOCKERS.md`: anything that needs the human (keys, accounts, approvals), each with the exact ask
   - `FEEDBACK.md`: every friction point, bug, doc gap or delight with Token Factory, Nebius
     AI Cloud, Nemotron or Tavily, logged as it happens. This becomes the submission's feedback section.
3. **Never stall on a missing credential.** Build against a mock that has the same interface, put the
   ask in `BLOCKERS.md`, and continue. Swap in the real connector when the key arrives.
4. **Do not cut features.** If something fights you for more than about 3 serious attempts, ship a
   simpler implementation behind the same interface, note it in `DECISIONS.md` as "revisit", carry on,
   and come back to it in Stage 15.
5. **Commits:** small and frequent, one per verified step, with conventional messages (`feat:`,
   `fix:`, `test:`…). **Never add AI attribution of any kind**: no `Co-Authored-By` trailers, no
   "Generated with" lines, not in commits, PRs, code or docs. Push over HTTPS to the GitHub account
   `Sumit99589` (git email `sumitbhatt9958@gmail.com`).
6. **Dev machine limits.** This is mandatory and also covered by `~/.claude/CLAUDE.md`: 4 cores and
   7.3 GB RAM, with Chrome and other sessions always running.
   - Run every build, test suite, bundler or browser inside
     `systemd-run --user --scope -q -p MemoryMax=<cap> -p MemorySwapMax=512M …`.
   - Run one heavy process at a time, and check `free -m` first. If less than 3 GB is available, stop and say so.
   - `next build`: `MemoryMax=3800M` with `NODE_OPTIONS=--max-old-space-size=1536`.
   - `next dev`/`next start`: `MemoryMax=1200M` with `--max-old-space-size=768`.
   - Headless Chromium/WebKit locally: `MemoryMax=1200M`, a single browser, and only for quick checks.
     Real browser fan-out runs in **GitHub Actions or Nebius**, never locally.
   - No local Docker; container images are built in GitHub Actions.
   - `/tmp` is a RAM-backed filesystem, so delete browser profiles and large temp files when done.
   - Never `pkill -f` a pattern that appears in your own command line. Use `fuser -k <port>/tcp`.
7. **Cost guard.** Total Token Factory credit is about $50: $25 from code `NEBIUS-DEVPOST-GLOBAL26`
   plus $25 from the Builders Program.
   - Cache every LLM call by hash of (model, messages, tools) in dev and in evals.
   - Develop and debug with Nano, and switch to Super or Ultra only once a flow works.
   - Each case has a token budget (config). Log cost per case to the DB and show it in the UI.
   - Never loop calls to Ultra.
8. **Secrets** live in `.env` (gitignored) with a committed `.env.example`. Never print secrets in logs.
9. **Testing:** pytest for the engine (unit and scenario), a small Playwright smoke test for the UI,
   and the eval harness (Stage 13). Keep `uv run pytest` green on every commit.
10. **When a stage is done**, update `PROGRESS.md`, commit, and move to the next stage without waiting for the human.

### A8. Human-only prerequisites (the human does these; the agent lists any missing ones in BLOCKERS.md)

1. **Token Factory:** create an account and an API key. Redeem `NEBIUS-DEVPOST-GLOBAL26` ($25) and
   join the Nebius Builders Program (another $25, plus Tavily credits).
2. **Nebius AI Cloud:** create a project, install and configure the `nebius` CLI (`nebius profile
   create`), and confirm Serverless Jobs can pull a public GHCR image. Note the project ID.
3. **Tavily** API key.
4. **Stripe** account in **test mode**: secret key, publishable key, webhook signing secret.
5. **GitHub:** two public repos, `whydunit` and `acme-demo`, plus a fine-grained token for
   `acme-demo` with contents, pull requests and actions permissions (read and write).
6. **Vercel:** two projects, Acme (from `acme-demo`) and the Whydunit UI. Create a Vercel API token
   for reading deployments.
7. **Neon:** one Postgres project and its connection string.
8. **Object storage bucket** with S3 keys.
9. **Devpost:** register and join the hackathon. **YouTube:** a channel for the video.

---

## PART B — Sequential build stages

### Stage 1 — Repo scaffold, model client, smoke tests

**Goal:** a clean monorepo with working, cost-tracked calls to all four Nemotron models.

Build:
- The `whydunit` repo layout:
  ```
  engine/            # Python package: api/, agents/, connectors/, analysis/, runtime/, fixtures/, evals/
  ui/                # Next.js app
  packages/snippet/  # TS tracking + rrweb snippet
  runner/            # Playwright runner (flows + replay rendering), Dockerfile, job entrypoint
  config/            # models.yaml, budgets.yaml, company_profile.yaml, incidents.yaml
  docs/              # architecture.md, video-script.md, devpost.md
  .github/workflows/ # ci.yml, runner-image.yml, simulator.yml (Stage 3)
  LICENSE (MIT), README.md, PROGRESS.md, DECISIONS.md, BLOCKERS.md, FEEDBACK.md, .env.example
  ```
- `engine/runtime/llm.py`:
  - one client for Token Factory, based on `openai.AsyncOpenAI(base_url=…, api_key=NEBIUS_API_KEY)`
  - role-based model selection (`nano | super | ultra | omni`), read from `config/models.yaml`
  - a reasoning on/off switch, retries with backoff, timeouts, a disk/DB response cache, and a token and cost meter (prices in config)
- `scripts/discover_models.py` calls `GET /v1/models`, prints the Nemotron IDs, and writes a
  suggested `models.yaml`.
- `scripts/smoke_llm.py`:
  - text completion on Nano, Super and Ultra
  - a tool call on Nano that returns valid JSON for a dummy tool
  - an image-description call on Omni (send a PNG as a base64 data URL)
  - prints latency, tokens and cost for each
- CI (`ci.yml`) runs ruff and pytest for the engine, plus a typecheck and lint for the UI.

**Done when:** the smoke script passes for all four roles, model IDs are pinned, CI is green, and the
first entries are in `FEEDBACK.md`.

### Stage 2 — Acme sandbox startup, snippet and ingest

**Goal:** a believable little SaaS that emits real funnel data and real session recordings into Whydunit.

Build:
- **`acme-demo` repo**: a Next.js app for a fictional product (name it, e.g. "Acme Notes"). Pages:
  - landing
  - pricing
  - **signup form**
  - onboarding
  - **checkout**: a server route creates a Stripe customer and subscription in test mode from a supplied test PaymentMethod
  - help/contact form, which writes to Acme's own helpdesk table
  - a cookie banner
  
  Plus an `/api/health` route. Deploy it on Vercel from `main`, so **every merge creates an immutable Vercel deployment URL**. The Deploy detective depends on this.
- **Acme's helpdesk and reviews tables** (in Acme's own Postgres schema or the shared Neon DB under an `acme` schema). These are the Voice detective's data.
- **`packages/snippet`**:
  - `whydunit.init({key})` auto-captures `page_view`.
  - `track(name, props)` records `signup_started`, `signup_completed`, `checkout_started`,
    `payment_succeeded`, `payment_failed`.
  - It adds browser, OS, device, viewport, UTM/channel, and an anonymous user/session id.
  - **rrweb** records a configurable sample of sessions and uploads them in chunks.
  - It is built into a single script and added to Acme.
- **Engine ingest API**: `POST /ingest/events` (batched) and `POST /ingest/replay` (chunks to blob
  storage plus a metadata row), with project API keys and basic rate limiting. Country comes from
  request headers (Vercel provides geo headers) or from a simulator-provided field.
- **DB schema** (Alembic migrations): projects, events, sessions, replays, deployments_cache, cases,
  case_events (append-only), evidence, hypotheses, findings, verdicts, fixes, llm_calls (cost).

**Done when:** a real browser visit to production Acme shows events and a replay in the DB and the
blob store, a Stripe test-mode subscription appears in the Stripe dashboard, and a helpdesk message
lands in the table.

### Stage 3 — Live world simulator (START IT AND LEAVE IT RUNNING)

**Goal:** about 7+ days of **real, correctly time-stamped history** across real systems, with three
real incidents planted at a scheduled time. The flagship demo video is recorded on this world.

Build:
- `simulator/` in the whydunit repo, run by `.github/workflows/simulator.yml` on a cron (every 10–15
  minutes). Public repos get free Actions minutes.
- **Each tick generates:**
  - **Synthetic visitors.** Volume follows a daily and weekly curve. The mix covers devices
    (desktop, iPhone Safari, Android Chrome), countries, and channels (organic, paid, referral).
    Paid traffic volume is read from the **mock ads platform's** live state, so a budget cap really
    reduces paid traffic.
  - **Funnel events** sent through the real ingest API. For each synthetic visitor, the signup
    success probability depends on the **real health of production Acme for that browser**. A
    small Playwright step in the same workflow runs the signup flow on production in Chromium
    (desktop), WebKit (iPhone 15) and Chromium (Pixel), and caches pass/fail per browser for the
    tick. If production is broken on WebKit, synthetic Safari visitors fail. Ground truth stays
    consistent with reality.
  - **Real Playwright sessions** (2–4 per tick) through production Acme with the snippet active, so
    there are **real rrweb recordings**, including real failed attempts with repeated taps after
    the bug ships.
  - **Real Stripe test-mode payments** for a sample of "paid" conversions through Acme's checkout
    route. Normal attempts use `pm_card_visa` and similar. During the payments incident, a share of a
    targeted segment uses decline test PaymentMethods (`pm_card_chargeDeclined`,
    `pm_card_chargeDeclinedInsufficientFunds`, and so on), so Stripe holds **real declines with
    decline codes**.
  - **Support tickets and app reviews.** Nano writes them in a realistic voice, at a normal background
    rate plus incident-related spikes ("can't tap Sign up on my iPhone").
- **Mock ads platform**, a small FastAPI service in `engine/mock_ads/`:
  - Its API is shaped like Google Ads reporting: campaigns, daily budget, cost, impressions, clicks,
    budget-limited status, and a **change history** like Google Ads change events.
  - It **also has a simple web dashboard** (charts and tables) that is used later to demo
    screen-reading.
  - It is labelled "simulated" everywhere in the UI and the video.
- **`config/incidents.yaml`** holds the incident schedule as offsets from the simulator start. The
  three planted incidents:
  1. **Code bug.** At T+4d a scheduled workflow merges a prepared branch into `acme-demo/main`. It is a
     realistic refactor that breaks signup **only on WebKit/Safari**.
     - First choice: wrap form hydration in a browser API that WebKit lacks, such as
       `requestIdleCallback`. Check on caniuse that Safari still lacks it.
     - Verify with Playwright: WebKit fails, Chromium passes.
     - If no engine-specific API is reliable, use a mobile-viewport bug instead: the new sticky cookie
       banner covers the submit button, so the click gets the "element intercepts pointer events"
       error.
     - Record the chosen variant in `DECISIONS.md`.
  2. **Ads budget cap.** At T+4.5d a "teammate" lowers the main campaign's daily budget in the mock.
     It then hits its cap around midday every day, and paid traffic falls.
  3. **Payment declines.** From T+5d, issuer-side declines for cards from one country segment rise
     from about 3% to about 18%.
- **Ground truth file:** the simulator writes the true incident times and effects to
  `simulator/ground_truth.json`, which is used later to score the live case.
- **Self-healing:** the Safari failure clears automatically when production passes WebKit again
  (after Whydunit's fix PR merges). Synthetic ad traffic recovers when the budget is restored, and
  declines clear on a schedule or when the "fix" action is approved. This makes the **recovery real**.

**Done when:** the workflow runs on schedule without errors for 6 consecutive ticks, data is
accumulating in all systems, and the incident schedule is committed. Record the simulator start time in
`PROGRESS.md`. **Leave it running. Then continue with Stage 4 while history builds.**

### Stage 4 — Fixture worlds (deterministic, back-dated, plantable)

**Goal:** fast, free, repeatable worlds for development, tests, evals, and a judge "playground".

Build:
- `engine/fixtures/world.py` generates a complete world into a duckdb file, or a separate Postgres
  schema, for any date range. The world includes:
  - events and sessions
  - deployments, as references to **real pre-built Acme deployment URLs**: build and keep three
    permanent Vercel deployments of Acme ("healthy", "safari-broken", "slow-checkout") so flow runs
    stay real even in fixture worlds
  - payments (a synthetic table with Stripe-like shape)
  - ads data and ads changes
  - tickets and reviews
  - recorded Tavily responses (vcrpy cassettes)
  - holidays and status-page incidents
- An **incident library**, each with a parameterised effect and ground truth: `deploy_bug(browser)`,
  `ads_budget_cap`, `payment_declines(segment)`, `public_holiday(country)`,
  `dependency_outage(service)`, `competitor_launch`, **`tracking_bug`** (the snippet stops sending
  `signup_completed` but Stripe revenue is normal, so it's a measurement problem and not a real drop),
  `seasonality_only`, and `noise_only` (no real change).
- A CLI: `uv run whydunit world create --incidents deploy_bug:webkit,ads_budget_cap --start … --days 14`.

**Done when:** worlds generate in under 30 s, and pytest asserts that every incident's signal is
present in the generated data.

### Stage 5 — Evidence layer and connectors (the ladder)

**Goal:** detectives can ask for evidence by kind and get uniform, cited, tiered results.

Build:
- `engine/connectors/base.py`:
  - a `Connector` protocol with `kinds`, `tier`, `available()` and `fetch(kind, window, filters) -> EvidenceBundle`
  - an `EvidenceBundle` containing id, kind, connector, tier, query, window, data reference
    (rows/blob), human-readable summary, artifacts (screenshots, diffs, links) and a fetched_at timestamp
  - a registry that resolves the best available connector per kind, plus a fixture mode that routes
    every kind to the fixture world
- **Tier 1 connectors (real APIs):**
  - `WhydunitEvents` (own DB)
  - `Replays` (own DB plus blobs)
  - `GitHub` (commits, compare, PRs on `acme-demo`)
  - `Vercel` (list production deployments with git SHA and URL)
  - `Stripe` (PaymentIntents and Charges with outcome and decline codes, filtered by creation time)
  - `MockAds` (Google-Ads-shaped API)
  - `Helpdesk` and `Reviews` (Acme tables)
  - `Tavily` (`search` with news topic and time window, and `extract`)
  - `Holidays` (date.nager.at public API)
  - `StatusPages` (Atlassian Statuspage JSON `…/api/v2/incidents.json` for dependencies listed in
    `company_profile.yaml`, e.g. githubstatus.com and vercel-status.com)
- A `GoogleAds` connector stub with the same interface as MockAds, documented as needing a developer
  token. It does not need to work.
- Tiers 2–6 come in Stage 12. Leave clean extension points.

**Done when:** pytest covers each connector, with HTTP mocked or cassettes recorded, and a script
prints one real evidence bundle per kind from the live world.

### Stage 6 — Analysis toolkit (deterministic statistics)

**Goal:** all numbers the product shows come from tested code.

Build in `engine/analysis/`:
- **Metric definitions** (config): the headline is **new paid subscriptions per day**, plus
  supporting metrics like visitors, signup rate and payment success rate.
- **Change detection:** compare a baseline window with the incident window, run changepoint detection
  (CUSUM or Bayesian online; keep it simple and tested), and **flag drops that are within normal
  variance**.
- **Funnel decomposition:** paid subs = traffic × signup rate × checkout rate × payment success
  rate. Use a **log decomposition**, so the change in each factor adds up exactly to the total change.
- **Segment drill-down:** for each factor, rank segments (browser, OS, device, country, channel,
  plan) by how much they contribute to its change, using mix versus rate effects.
- **Counterfactual and Shapley attribution:**
  - Given a set of hypotheses, each mapping to a (factor, segment, window) "effect", compute the
    metric with any subset of effects removed (restored to baseline).
  - Shapley values over the hypotheses give each one a **fair share** of the drop. Exact
    computation is fine for 7 or fewer hypotheses.
  - The **unexplained** share is the residual.
- **Bootstrap** confidence intervals for each share.
- **Session heuristics:** rage clicks (3 or more clicks on the same element within 1 s), dead clicks
  (a click with no DOM change or navigation within 1 s), and form abandonment, computed from rrweb
  event streams.

**Done when:** unit tests on fixture worlds recover the ground-truth factors, and the Shapley shares
come within ±5 percentage points of ground truth on the 3-incident fixture.

### Stage 7 — Agent runtime and the first detective

**Goal:** a reliable loop for one detective, from case to evidence to findings, streamed as events.

Build in `engine/runtime/` and `engine/agents/`:
- **Pydantic schemas:**
  - `Case` (metric, question, window, status)
  - `Finding` (claim, kind: observed | inference, evidence_ids, metrics_refs, confidence)
  - `Hypothesis` (statement, effect spec for attribution, supporting/contradicting evidence, status)
  - `DetectiveReport`
  - `Question` / `Answer` (for cross-examination)
- **Detective loop:** a system prompt, an allowed tool set (connector fetches plus analysis
  functions), the Nano model for tool loops, and Super for the final report. Each detective has
  max-steps and token budgets, and returns a strict JSON `DetectiveReport`.
- **Validator** (code, not a model):
  - It rejects findings whose evidence IDs don't exist or don't belong to this case.
  - It rejects narrative numbers that don't match the referenced metrics (extract numbers and
    compare within tolerance).
  - It downgrades confidence for low-tier evidence.
  - It re-prompts once with the reason. On a second failure, the finding goes to "suspicions".
- **Case event log:** every step (detective started, tool call, evidence pinned, finding, question,
  answer, verdict, fix, verification) is appended to `case_events` and **streamed via SSE**
  (`GET /cases/{id}/stream`). Replay mode is the same log replayed with its original timing.
- **The Funnel detective** is first: it calls the decomposition and segment drill-down and reports
  findings.
- A CLI to run it: `uv run whydunit case open --world fixture:3inc --metric paid_subs`.

**Done when:** the Funnel detective correctly reports "signup rate fell, concentrated in iOS Safari"
and "paid traffic fell" on the 3-incident fixture, with valid evidence, events in the DB, and the SSE
stream readable with curl.

### Stage 8 — The remaining six detectives

**Goal:** a full team, run in parallel. Each detective has its own tools and an honest
`cannot_determine` path.

- **Deploy detective**
  - Lists production deployments in the window (Vercel plus GitHub).
  - Asks the **runner** to execute the signup flow on each deployment URL across the browser matrix.
    The runner returns pass/fail, the error, a screenshot and timing.
  - Finds the first failing deployment, fetches the GitHub compare diff against the previous one,
    and has Super pinpoint the suspect lines.
  - Has Omni read the failure screenshot ("the button is visible but nothing happens", or "covered by banner").
- **Runner** (`runner/`)
  - A Python + Playwright container with two entrypoints: `run-flows` (a JSON spec of flows, URLs
    and browsers, producing results and screenshots in the bucket) and `render-replay` (rrweb
    recording IDs, producing keyframes in the bucket).
  - Built by `runner-image.yml` into GHCR and launched as a **Nebius Serverless Job**, triggered via
    the Nebius CLI/API from the engine. Polls or waits for completion.
  - Also runs as an HTTP service for an optional Nebius Serverless Endpoint.
  - Has a local fallback mode (capped, one browser) for development only.
  - Records everything about getting the Nebius Job working in `FEEDBACK.md`.
- **Session detective**
  - Picks up to about 10 failed-signup sessions in the affected segment and a few healthy controls.
  - The runner renders keyframes (on every click, every N seconds, and at the end).
  - Session heuristics (Stage 6) supply rage and dead clicks.
  - **Nano Omni** describes what the user experienced, frame by frame.
  - Reports the pattern, with frames as evidence.
- **Payments detective:** Stripe outcomes by day, decline-code mix, and card country/brand segments
  compared with the baseline. Separates issuer declines from Acme-side errors.
- **Ads detective:** spend, impressions, clicks and budget-limited status by campaign and day, plus
  the change history. Spots "budget lowered on day X, campaign capped by noon every day since".
- **Voice detective**
  - Nano clusters tickets and reviews by topic.
  - Spike detection per topic against the baseline.
  - Pulls representative quotes, which become evidence.
  - Runs a Tavily search for public chatter about the product. For fictional Acme this will usually
    find nothing; it should say so plainly.
- **World detective (Tavily, which secures the bonus)**
  - Generates queries from `company_profile.yaml` (industry, competitors, dependencies, top
    countries) for the window.
  - Uses Tavily search (news topic, time-bounded) and extract.
  - Checks holidays and status pages.
  - Reports "No external cause found; checked: …" with links. Absence of evidence must be shown as
    an explicit checked-list.
- All seven run **concurrently** (asyncio) with per-detective budgets. The case board will show them
  working at once.

**Done when:** on the 3-incident fixture, each detective returns a valid report. On the live world
(after T+5d), the Deploy detective finds the real culprit deployment through a real Nebius Job, and
the Session detective's Omni description mentions the failed taps.

### Stage 9 — Lead detective, cross-examination, attribution and verdict

**Goal:** turn seven reports into one defensible answer.

Build `engine/agents/lead.py`, using Ultra with reasoning on:
1. **Opening brief:** reads the metric decomposition (Stage 6) and the first-round reports, and
   lists candidate hypotheses. Each must map to an **effect spec** (factor + segment + start time)
   so it can be attributed.
2. **Cross-examination:** up to 3 rounds. The lead sends `Question`s to specific detectives, e.g.:
   - to Funnel: "is the Safari drop present before deploy #N?"
   - to Deploy: "does deploy #N–1 pass WebKit?"
   - to World: "any Safari or iOS release that week?"
   
   Each detective answers with **new evidence or `cannot_determine`**. Contradictions are shown,
   not hidden. The thread is streamed.
3. **Judgement:** hypotheses are marked supported, rejected or inconclusive. Code enforces that a
   supported hypothesis has observed evidence of both the **mechanism** and the **timing**.
4. **Attribution:** call Shapley attribution (Stage 6) on the supported hypotheses, giving shares with
   confidence intervals and an unexplained share.
5. **Verdict:**
   - the ranked causes with share and confidence, the evidence trail and a "how we know"
   - recommended actions
   - "not checked / no access" items
   - special verdicts when they apply: **"no real drop: within normal variance"** and **"measurement
     problem, not a business drop"** (tracking_bug)
   
   The narrative is generated by Ultra, then checked by the number validator.

**Done when:** on the 3-incident fixture the verdict names all three causes with shares within ±5pp
of ground truth and makes no false accusations. `noise_only` gives "no real drop", and `tracking_bug`
gives a measurement verdict.

### Stage 10 — The case board UI (the Design criterion lives here)

**Goal:** a polished product that a judge understands in 10 seconds, not a debug console.

Build in `ui/` (Next.js). Use the `frontend-design` and `motion-ui` skills for visual direction:
a detective "case board" feel, but professional and calm (Linear/Vercel-grade), with dark and light
themes. Pages:
- **`/` Landing**
  - A one-line pitch and a 20-second looping preview.
  - Buttons: "Watch a solved case" (replay), "Investigate a fixture world" (playground), "Connect your product".
- **`/cases/[id]` Case board** (the hero screen):
  - **Header:** the metric, the drop ("−23% paid subscriptions, Tue → Thu"), the window, status
    (Investigating → Verdict → Fixing → Verifying → Closed) and cost so far.
  - **Metric chart** with annotations: deploy markers, ads changes, decline spike, holidays.
  - **Detective roster:** seven cards with live status, current action, and a mini log.
  - **Evidence wall:** pinned evidence cards with a source-tier badge, confidence, thumbnails
    (screenshots, keyframes), and diff snippets and links. Click any finding to highlight its evidence.
  - **Interrogation thread:** the lead's questions and the detectives' answers, in real time.
  - **Blame waterfall:** Shapley shares with confidence-interval whiskers and an explicit grey
    "unexplained" bar.
  - **Verdict panel:** the narrative, "how we know", and "not checked".
  - **Fix and Verify panel** (Stage 11).
  - **Replay mode:** replays a stored case at 1×/4× speed from the event log.
- **`/cases`:** a list of cases with status and auto-opened badges.
- **`/connect`:** each evidence kind with its connector ladder and which tier is active (Stage 12).
- **`/playground`:** pick a fixture world, toggle incidents to plant, and start the investigation.
  This is the judge-interactive mode.
- **`/evals`:** the public eval results table (Stage 13).
- Mobile: the case board stacks vertically and is readable on a phone. Check at 390 px width.

**Done when:** the full 3-incident fixture case plays live and in replay with no layout breakage, a
UI Playwright smoke test passes (under memory caps), and screenshots at desktop and mobile widths look
like a product.

### Stage 11 — Fix, verify, close, and always-on watching

**Goal:** close the loop, which is a recurring pattern in past winners.

Build:
- **Code fixes:**
  - Super writes a patch for the culprit diff, which is applied in a temporary clone of `acme-demo`.
  - A **PR is opened** via the GitHub API with an evidence-linked description. Vercel builds a
    **preview deployment** automatically.
  - The runner re-runs the failing flow across the browser matrix against the preview URL.
  - The PR is marked **verified** only if all browsers pass. Otherwise Super revises, up to 2 tries.
  - The human merges (or presses "Approve & merge" in the UI). That calls the GitHub merge API and
    is approval-gated.
- **Config fixes** (approval-gated):
  - "Restore ads budget" shows a diff (old value to new) and an Approve button that calls the mock
    ads API.
  - For payment declines, the action is a recommendation (enable retries or an alternative payment
    method for the affected segment). Approval toggles the simulator's mitigation flag. The UI states
    clearly that this is simulated.
- **Verification:**
  - After each fix, the case moves to **Verifying**.
  - The watcher compares fresh data with the counterfactual expectation, and the case closes once
    each cause's affected factor is back within its baseline interval.
  - It **re-opens with an explanation** if recovery doesn't happen.
  - On the live world, recovery is real because the simulator reacts to real production health and
    real ads state.
- **Always-on watcher:**
  - A scheduled job (GitHub Actions cron or a Nebius Serverless Job) runs change detection on the
    headline metrics.
  - It **auto-opens a case** when a significant drop is detected, and notifies via a webhook (Slack-
    compatible payload, optional).
  - It is marked "auto-opened" on the board. This is the "workflow that runs itself" from the track
    description.

**Done when:** on the live world, after the incidents have run:
1. The watcher auto-opens the case.
2. The investigation finds all three causes.
3. The fix PR is opened and verified on the preview, then merged.
4. The ads budget is restored by approval.
5. The metric visibly recovers in the chart.
6. The case closes by itself.

Save that case: it is the flagship replay and the video source.

### Stage 12 — The rest of the connector ladder and the Connect page

**Goal:** prove that Whydunit works even with tools that have no API.

Build:
- **Tier 2:**
  - A `Warehouse` connector, a generic SQL source with table mapping config, so a Postgres or
    BigQuery-style warehouse can feed any evidence kind.
  - A `PyAirbyte` connector that pulls one real source end-to-end, e.g. a GitHub or Stripe stream
    through PyAirbyte, to show the long-tail path. Document how to add others.
- **Tier 3:** `CSVUpload`. The user uploads an export, **Nano maps columns** to the evidence kind's
  schema, a preview is confirmed in the UI, and the data is stored as evidence.
- **Tier 4:** `ScreenReader`.
  - The browser runner logs into a vendor dashboard read-only (demo: the **mock ads dashboard**
    with its API switched off in "no-API mode").
  - It screenshots the relevant views.
  - **Nano Omni extracts the table and chart values** into structured rows, tagged "screen-read,
    medium confidence".
  - It shows the screenshot next to the extracted rows for audit.
- **Tier 6:** `AskHuman`. When no connector can supply a kind, an "Evidence request" card appears in
  the case with an upload button, and the investigation continues without it.
- **`/connect` page:** each evidence kind shows its ladder, the active tier, and a "test connection"
  button.

**Done when:** with the ads API disabled, the Ads detective still finds the budget cap by screen
reading and says so with its confidence downgraded. A CSV upload of Stripe-like payments is correctly
mapped and used.

### Stage 13 — Evaluation harness (credibility for the Technological Implementation criterion)

**Goal:** a published, reproducible accuracy table.

Build `engine/evals/`. Each fixture scenario has ground truth, and Tavily and other HTTP calls use
recorded cassettes so runs are deterministic. The LLM cache stays on for re-runs.

Scenarios (at least 10):

| ID | Scenario |
|---|---|
| S1 | Deploy bug only |
| S2 | Ads cap only |
| S3 | Payment declines only |
| S4 | **The flagship: all three causes** |
| S5 | A public holiday causes the drop. The red herring is a harmless deploy that same day, and it must **not** be accused. |
| S6 | Noise only: there is no real drop |
| S7 | A dependency outage on a status page |
| S8 | A competitor launch, found via Tavily |
| S9 | Tracking bug (a measurement problem) |
| S10 | Seasonality plus a small real deploy bug |

**Metrics:**
- top-cause accuracy
- mean absolute error of the shares (pp)
- **false accusation rate**
- correct abstention ("no real drop", "cannot determine")
- time per case and cost per case

Outputs: `evals/results.json`, a README table, and the `/evals` page.

**Done when:** all scenarios run in one command, results are committed, and failures are analysed
in `DECISIONS.md`. Fix prompts and logic until the false accusation rate is 0 on the suite and
top-cause accuracy is at least 9/10. Record honestly if it isn't.

### Stage 14 — Hosting for judges (free and available until Dec 15)

**Goal:** a demo that is always up, cheap to run, and impossible for judges to break.

Build and deploy:
- **UI** on Vercel. **Engine** as a container:
  - First choice: a **Nebius Serverless Endpoint**, but only if its always-on cost over about 7
    weeks fits the remaining credits. Compute this and write it in `DECISIONS.md`.
  - Otherwise host it on a free-tier container platform, with Nebius Serverless **Jobs** kept for
    the runner (this still satisfies "runs on Nebius" via Jobs, and Token Factory calls satisfy the
    runtime requirement anyway).
- **Judge modes:**
  - **Replay** (zero cost; the flagship live case from Stage 11)
  - **Playground** (fixture worlds, real Nemotron and Tavily calls)
  - **Live Acme** (the real world: read-only investigation, with the simulator still running in a
    healthy steady state)
- **Guards:**
  - a per-IP rate limit and a daily global budget for Playground runs
  - when the budget is exhausted, the UI falls back to Replay with a friendly banner
  - no login required; if any login is added, its credentials go in the testing instructions
- **Health:** a status endpoint, plus an uptime check (a GitHub Actions cron that hits the URLs
  daily and opens an issue on failure).
- Turn the simulator down to a low steady rate after the video is recorded, to save credits.

**Done when:** a fresh browser session with no credentials can replay the flagship case and run a
Playground case end to end on the public URL. Cost per Playground case is measured and recorded.

### Stage 15 — Hardening and revisits

- Work through every "revisit" item in `DECISIONS.md`.
- Add error states to every UI panel (connector down, budget hit, model timeout), with a graceful
  partial verdict.
- Run a performance pass: target a flagship case wall-clock time under about 4 minutes live and under
  90 s in Playground with small fixtures.
- Security: read-only scopes by default, approval gates on every write, secrets never sent to the
  client, and checked input on uploads.
- Make the README complete enough that a stranger can run it locally (`.env.example`, seed scripts,
  fixture mode with no external keys except `NEBIUS_API_KEY`).

### Stage 16 — Submission package

Build in `docs/`:
- **`architecture.md` and a README diagram:**
  - detectives → evidence layer → connector ladder → sources
  - lead detective → attribution → verdict → fix/verify
  - where each Nemotron model and each Nebius service is used
- **`video-script.md`** (target 2:45, never over 2:59). Record it on the flagship replay:
  - **0:00–0:15 — hook.** "Paid signups fell 23% this week. Eight dashboards. Where do you even start?"
  - **0:15–0:35 — the case opens.** The watcher auto-opens the case and seven detectives launch in
    parallel.
  - **0:35–1:30 — the investigation, as close-ups:**
    - The Deploy detective's WebKit failure screenshot, run as a real Nebius Job.
    - The Session detective: Omni describes repeated taps on a dead button.
    - The Ads detective finds the cap. The Payments detective finds the decline spike.
    - The World detective: "Nothing external. Checked: news, holidays, status pages" (Tavily).
    - The lead detective's interrogation thread.
  - **1:30–1:55 — the verdict.** The blame waterfall (e.g. 58% / 31% / 9% / 2% unexplained) and
    "how we know".
  - **1:55–2:25 — the fix.** The fix PR is verified on the preview, the ads budget is approved, the
    metric recovers, and the case closes.
  - **2:25–2:45 — credibility:**
    - Nemotron Nano/Super/Ultra/Omni on Token Factory, Nebius Serverless Jobs, Tavily
    - the eval table (accuracy, zero false accusations)
    - screen-reading a no-API dashboard
  - **2:45 — close.** "Whydunit. Know why, fix it, prove it."
  - Say plainly on screen: "Real: GitHub, Vercel, Stripe test mode, analytics, sessions, Tavily.
    Simulated: ad platform and traffic."
- **`devpost.md`:**
  - the problem, with a credible audience (founders, PMs, growth teams at startups without data
    analysts)
  - what it does, how it's built, and how Nemotron is used (per model, with why)
  - how Token Factory and Nebius AI Cloud are used, and how Tavily is used
  - the eval results, challenges, and what's next
  - **the feedback section from `FEEDBACK.md`** (specific, constructive, with reproduction steps;
    it competes for Most Valuable Feedback)
  - testing instructions for judges
- A **checklist** before submitting:
  - [ ] the repo is public
  - [ ] the MIT licence is visible in About
  - [ ] the demo URL works logged-out
  - [ ] the video is under 3:00, public on YouTube, with no copyrighted music or third-party logos
  - [ ] the track is "Best Apps and Agents"
  - [ ] the Tavily runtime call is visible in the code and the video
  - [ ] Nemotron usage is explained
  - [ ] the feedback section is filled in
  - [ ] testing instructions are included
  
  Submit well before Oct 30, 10:00 AM PDT (10:30 PM IST). Devpost allows editing until the deadline.

### Stage 17 — Extensions (only after Stage 16 is complete and submitted in draft)

Same engine, new **case templates**. Each one has a trigger question, a detective set, an evidence
standard and a verdict format. Keep each one specific, never a generic "audit everything":
- **"Why is checkout slow?"** Uses the permanent "slow-checkout" Acme deployment. The detectives cover
  frontend bundle, API traces, database queries and the AI call. The verdict is a latency budget per
  layer plus before/after benchmarks.
- **"Why is our AI/cloud bill up?"** Ties cost to specific code paths, with a recommendation where
  Nemotron Nano is good enough.
- **"Whydunit for code: Launch Day":** domain-expert agents (frontend, backend, database, cloud, AI)
  question each other about the promises each layer makes to the others. A simulated launch swarm and
  attacker agents run against a sandbox clone. Each finding is proven by running something, then
  fixed and re-run until it survives.
- Real connectors: GA4, PostHog, Google Ads (developer token), Intercom/Zendesk, Slack alerts.

---

## PART C — Reference

### C1. Repository map (target)

```
whydunit/
  engine/
    api/            # FastAPI: ingest, cases, stream (SSE), fixes, playground, connect, evals
    agents/         # funnel.py deploy.py session.py payments.py ads.py voice.py world.py lead.py fixer.py
    connectors/     # base.py registry.py + one file per connector + tiers 2-6
    analysis/       # changepoint.py decompose.py segments.py shapley.py bootstrap.py sessions.py
    runtime/        # llm.py orchestrator.py validator.py events.py budgets.py cache.py
    fixtures/       # world.py incidents.py
    mock_ads/       # Google-Ads-shaped API + dashboard
    evals/          # scenarios/, run.py, results.json
  simulator/        # tick.py, incidents.yaml loader, ground_truth.json
  runner/           # flows/, replay/, Dockerfile, entrypoints
  packages/snippet/
  ui/
  config/
  docs/
acme-demo/          # separate repo: the sandbox startup
```

### C2. Detective tool contracts (summary)

| Detective | Evidence kinds | Key tools | Model |
|---|---|---|---|
| Funnel | funnel_events | decompose, segment_drilldown, changepoint | Nano loop, Super report |
| Deploy | deploys | list_deployments, run_flows (Nebius Job), git_compare, read_screenshot | Nano loop, Super diff analysis, Omni screenshots |
| Session | sessions | select_sessions, render_keyframes (Nebius Job), session_heuristics, describe_frames | Omni + Nano |
| Payments | payments | payment_outcomes, decline_mix, segment_compare | Nano loop, Super report |
| Ads | ad_performance, ad_changes | campaign_report, change_history | Nano loop, Super report |
| Voice | support_tickets, reviews, world_news | cluster_topics, topic_spikes, quotes, tavily_search | Nano |
| World | world_news, holidays, dependency_status | tavily_search, tavily_extract, holidays, status_incidents | Nano loop, Super report |
| Lead | all reports | ask(detective, question), attribute(hypotheses), verdict | Ultra |
| Fixer | deploys | write_patch, open_pr, run_flows(preview), merge (gated) | Super |

### C3. Risk register and fallbacks

| Risk | Fallback |
|---|---|
| Ultra or Omni model IDs unavailable or flaky on Token Factory | Lead runs on Super with reasoning on. Omni-only steps use rule-based session heuristics plus a Super text summary. Log it in FEEDBACK.md. |
| Omni is image-only | Already the design (keyframes), so no change |
| Nebius Serverless Job setup is slow or blocked | Runner runs in GitHub Actions (still real browsers) while the Job path is fixed. Token Factory calls keep the project eligible. Keep trying the Job path, because it's worth judge points. |
| The WebKit-only bug doesn't reproduce in Playwright WebKit | Use the mobile-viewport banner-overlap bug instead (Stage 3) |
| Live simulator history is too short when it's time to record | Record the flagship on the longest live window available. Playground and evals still use full fixtures. |
| Credits run low | LLM cache, Nano for development, per-case budgets, and Replay as the default judge mode. Ask for credits on the Nebius Discord / office hours. |
| Too many integrations | The ladder plus mocks with identical interfaces mean every detective always has *some* source. Real ones get swapped in as keys arrive. |
| Judges think the data is fake | Be explicit about what is real and what is simulated. The flagship case runs on real GitHub, Vercel, Stripe test mode and browsers. Show the eval table. |

### C4. Kick-off prompt for Claude Code

Run Claude Code from inside the `whydunit` repo, with this plan saved as `PLAN.md`, and give it:

> Read PLAN.md completely. Execute it stage by stage from the first stage not marked done in
> PROGRESS.md, following Part A's operating rules exactly (memory caps, no AI attribution, never
> block on credentials, keep PROGRESS/DECISIONS/BLOCKERS/FEEDBACK updated, commit after each verified
> step). Start the Stage 3 simulator as soon as its prerequisites exist and leave it running. Do not
> stop between stages; when a stage's "Done when" checks pass, continue to the next one.

When a session ends (context or turn limits), start a new one with: "Continue PLAN.md from PROGRESS.md."
