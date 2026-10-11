# Whydunit: Devpost submission

**Track:** Best Apps and Agents · **Bonus:** Best Use of Tavily

## Inspiration

When a startup's numbers drop, the cause is almost never in one place. Signups fall because a deploy broke a button
on Safari, *and* a teammate trimmed an ad budget, *and* one country's banks started declining cards. Product
analytics explain changes only within their own data; AI incident tools look only at infrastructure. Founders, PMs
and growth leads at startups without a data team lose days pulling eight dashboards together, and still end up
guessing which cause mattered most.

## What it does

Whydunit opens a **case** on a metric drop (or its watcher opens one by itself) and sends a team of seven detective
agents to investigate in parallel: **Funnel, Deploy, Session, Payments, Ads, Voice and World**. Each has its own tools
and asks for evidence by kind through a **connector ladder** (official API → warehouse → CSV export → screen reading
→ public web → ask a human), so it keeps working when a tool has no API.

A **lead detective** cross-examines them. Code throws out any claim without evidence or with a number that doesn't
match a computed metric. A cause is accepted only with an observed **mechanism and matching timing**. The drop is
then split between causes with **exact Shapley values over counterfactuals**, with confidence intervals and an honest
unexplained share. Whydunit **opens the fixes** (a pull request verified on the preview in five real browsers, an
approval-gated budget change) and **closes the case only when the metric has recovered**. It also knows when to say
"no real drop: within normal variance" and "measurement problem, not a business drop".

## How we built it

- **Engine:** Python 3.12, FastAPI, polars/DuckDB/numpy for analysis, Postgres (Neon), an asyncio orchestrator of
  our own with OpenAI-style tool calling against Token Factory, and an append-only case event log streamed over SSE.
- **Analysis (all code, all tested):** seasonally matched change detection with overdispersed Poisson variance and
  CUSUM timing; LMDI funnel decomposition (exact); mix/rate segment drill-down; counterfactual restoration with
  exact Shapley attribution and a parametric bootstrap; rage/dead-click heuristics from rrweb streams.
- **UI:** Next.js 16 case board: live roster, evidence wall with numbered markers, interrogation thread, blame
  waterfall, fix-and-verify panel, and replay of any case from its event log.
- **A real sandbox startup**, Acme Notes, on Vercel with Stripe in test mode, our tracking snippet and rrweb
  recordings, plus a **live simulator** (GitHub Actions) that plants three real incidents: a WebKit-only
  `requestIdleCallback` refactor merged via a real PR, an ad budget cut, and Brazilian card declines through Stripe's
  decline test cards.
- **Fixture worlds** with planted incidents and exact ground truth (common random numbers make every counterfactual
  world exact), used by tests, the playground and the eval harness.

## How we use NVIDIA Nemotron

| Model | Role | Why |
|---|---|---|
| **Nemotron 3 Nano** | Detectives' tool loops, ticket clustering, CSV column mapping, news relevance, simulator text | Cheap and fast for many small structured calls |
| **Nemotron 3 Super** | Each detective's final JSON report, diff reading, writing fix patches | Stronger reasoning where a wrong claim is costly; the validator re-prompts once |
| **Nemotron 3 Ultra** | The lead detective's verdict narrative, once per case | Best judgement for the one paragraph a founder reads; never looped |
| **Nemotron 3 Nano Omni** | Failure screenshots, session-replay keyframes, dashboard screenshots (screen-reading tier) | Vision is what lets Whydunit work on tools without an API |

Reasoning is switched on for Super and Ultra judgement calls and off for Nano loops (`chat_template_kwargs`).

## Nebius Token Factory and Nebius AI Cloud

- **Token Factory** serves every model call through one OpenAI-compatible client with role-based model selection,
  per-case cost metering shown in the UI, a response cache, role fallbacks and per-case budgets.
- **Nebius Serverless Jobs** run the browser runner image (Playwright with Chromium, WebKit and Firefox) to test
  every deployment and every fix preview across five browsers, render replay keyframes, and capture dashboards for
  screen reading.

## How we use Tavily

The World detective builds time-bounded news searches from the company profile (competitors, the industry,
dependencies' outages) and reports an explicit checked-list when nothing is found. The lead uses Tavily during
cross-examination to rule out alternatives ("any Safari or iOS release that week?"). The Voice detective searches the
public web for chatter about the product.

## Evaluation

Ten planted scenarios with exact ground truth, including a holiday with a red-herring deploy, a tracking bug and pure
noise. **Top cause right in 10/10, 0 false accusations, share error 0.17 pp, correct abstentions 2/2** (see the
README table and the `/evals` page).

## Challenges

- Making attribution trustworthy: naive counterfactuals over-credited the Safari bug by 17 points until downstream
  rates were shrunk only where an upstream factor is restored. It now matches exact ground truth within 1 point.
- Planting a bug that is genuinely WebKit-only: we probed Playwright's browsers in CI and found
  `requestIdleCallback` missing in WebKit 26.6 but present in Chromium and Firefox.
- Being honest without being useless: knowing when to say "no real drop" or "measurement problem", and naming real
  but small causes with a caveat instead of hiding them.

## What's next

Case templates on the same engine ("why is checkout slow?", "why is our AI bill up?"), and real connectors for GA4,
PostHog, Google Ads, Intercom and Slack.

## Feedback on Nebius and NVIDIA tools

## 2026-10-11

- **[Token Factory · docs] Model IDs for Nemotron 3 Ultra and Nano Omni are hard to find before signing
  up.** Nebius's own Nemotron page names the models but not their API IDs; we found
  `nvidia/Nemotron-3-Ultra-550b-a55b` and `nvidia/Nemotron-3-Nano-Omni` only on third-party router
  catalogs, with casing that differs from the lowercase IDs in Nebius examples
  (`nvidia/nvidia-nemotron-3-nano-30b-a3b`). *Suggestion:* publish a public model table with exact,
  copy-pasteable IDs, context length, modalities and price, and say whether IDs are case-sensitive.
- **[Token Factory · docs] Two base URLs appear in Nebius material** (`api.tokenfactory.nebius.com` and
  `api.tokenfactory.us-central1.nebius.com`) without a note on which to use. *Suggestion:* one canonical
  URL in the quickstart, with regional endpoints explained separately.
- **[Nemotron · docs] The reasoning on/off switch is documented per serving stack** (HF
  `apply_chat_template(enable_thinking=…)`, vLLM `chat_template_kwargs`) but we found no Token Factory
  page confirming which form it honours. *Suggestion:* a short "reasoning control" section in the Token
  Factory docs with an OpenAI-SDK snippet using `extra_body`.

- **[Nebius AI Cloud · Serverless Jobs docs] No documented way to read a job's status.** The "Manage jobs" page
  covers list, logs, cancel and delete, and mentions only that `COMPLETED` jobs are cancelled automatically.
  There is no `nebius ai job get` example and no list of states (pending/running/failed). An orchestrator that
  launches jobs programmatically has to infer completion some other way (we poll for the job's output file in
  object storage). *Suggestion:* document the job lifecycle states and a `job get --format json` example with the
  status field path.
- **[Nebius AI Cloud · Serverless Jobs docs] CPU-only jobs are under-documented.** `--platform` defaults to a GPU
  (`gpu-h100-sxm` / `gpu-h200-sxm`), and the jobs pages say CPU VMs "only support the regular type" but name no
  CPU platform or preset. A headless-browser workload (our runner) needs CPU only. *Suggestion:* add a CPU job
  example (platform + preset) to the quickstart.
- **[Nebius AI Cloud · CLI reference] Nice:** `job create --async --format 'jsonpath={.resource_id}'` returning
  just the job id makes scripting easy, and `--inject-file` / `--env-secret` cover config and secrets cleanly.

## Testing instructions for judges

No login is needed.

1. **Watch a solved case:** open the demo URL and click *Watch a solved case*: the flagship investigation replays at
   4× from its event log (free, always available).
2. **Run an investigation yourself:** *Playground* → pick a world (start with "Three things went wrong at once").
   Real Nemotron calls and a real Tavily search run; a case takes about a minute. Each visitor can open three cases an
   hour; if the day's budget is used up, the page points to the replay.
3. **The live world:** *Playground* → *Investigate the live Acme world* (read-only: fixes are shown, never applied).
4. **Evals:** */evals*. Every row links to its case.
5. **Connectors:** */connect* shows each evidence kind's ladder and which tier is active.

Demo URL: _(to be filled once deployed)_ · Repository: https://github.com/Sumit99589/whydunit (MIT)

## Submission checklist

- [ ] The repo is public
- [ ] The MIT licence is visible in the About section
- [ ] The demo URL works logged out
- [ ] The video is under 3:00, public on YouTube, with no copyrighted music or third-party logos
- [ ] The track is "Best Apps and Agents"
- [ ] The Tavily runtime call is visible in the code (`engine/connectors/tavily_conn.py`) and in the video
- [ ] Nemotron usage is explained (above)
- [ ] The feedback section is filled in (above)
- [ ] Testing instructions are included (above)
