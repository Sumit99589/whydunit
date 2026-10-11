# Whydunit

A team of AI detectives that finds out why your numbers dropped, proves it, fixes it, and confirms the fix worked.

*"Signups fell 23% since Tuesday."* A founder normally loses days digging through eight dashboards. Whydunit opens a
**case**, sends seven specialist detectives through deploys, the funnel, session recordings, payments, ads, support and
the news at once, has a lead detective cross-examine them, splits the blame between causes **with maths, not vibes**,
opens the fixes, and closes the case only when the metric has recovered.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents) on **Nebius Token Factory** with **NVIDIA
Nemotron** (Nano, Super, Ultra, Nano Omni), plus **Tavily** for the outside world.

## What makes it different

- **No proof, no finding.** Every claim cites evidence the system fetched or computed; code (not the model) rejects
  claims whose evidence doesn't exist or whose numbers don't match a computed metric.
- **Numbers come from code.** Change detection, funnel decomposition (LMDI), segment drill-down and attribution (exact
  Shapley values over counterfactuals, bootstrap confidence intervals) are deterministic and tested.
- **A cause needs a mechanism *and* matching timing**, confirmed by cross-examination, or it isn't blamed.
- **Honest about uncertainty**: an explicit unexplained share, "no real drop", "measurement problem, not a business drop",
  and a "not checked" list.
- **Closes the loop**: pull request verified on a preview across five browsers, approval-gated config changes, and a
  watcher that verifies recovery.
- **Works without APIs**: a connector ladder from official APIs down to warehouses, CSV exports, reading a dashboard
  screenshot with Nemotron Nano Omni, the public web, and asking a human.

## Evaluation

Ten planted scenarios with exact ground truth (`uv run whydunit evals run`):

| ID | Scenario | Verdict | Top cause right | Share error (pp) | False accusations | Time | Cost |
|---|---|---|---|---|---|---|---|
| S1 | Deploy bug only (Safari signup) | causes | yes | 0.0 | 0 | 3.4 s | $0.0000 |
| S2 | Ads budget cap only | causes | yes | 0.0 | 0 | 1.9 s | $0.0000 |
| S3 | Payment declines only (Brazil) | causes | yes | 0.0 | 0 | 2.2 s | $0.0000 |
| S4 | The flagship: all three causes | causes | yes | 0.4, 0.9, 0.4 | 0 | 3.8 s | $0.0000 |
| S5 | Public holiday, with a harmless deploy the same day | causes | yes | 0.0 | 0 | 2.4 s | $0.0000 |
| S6 | Noise only: no real drop | no real drop | yes | – | 0 | 1.6 s | $0.0000 |
| S7 | Payments provider outage on a status page | causes | yes | 0.0 | 0 | 1.8 s | $0.0000 |
| S8 | Competitor launch found in the news | causes | yes | 0.0 | 0 | 2.4 s | $0.0000 |
| S9 | Tracking bug: a measurement problem | measurement | yes | – | 0 | 2.9 s | $0.0000 |
| S10 | Weekend dip plus a small Firefox bug | causes | yes | 0.0 | 0 | 2.3 s | $0.0000 |

**Top-cause accuracy 10/10** · share MAE 0.17 pp · false accusations 0 (0%) · correct abstention 2/2 · missed causes 0 · mean 2.47 s and $0.0000 per case (deterministic mode)

Single-cause scenarios have a share error of 0 by construction; the flagship (S4) is the real test of attribution.

## Run it locally (no keys needed)

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm.

```bash
./scripts/dev_up.sh                       # embedded Postgres, migrations, fixture worlds, a first case
uv run whydunit serve                     # engine API on :8000
cd ui && pnpm install && pnpm dev         # case board on :3000 (proxies /engine to :8000)
```

Then open http://localhost:3000/playground and pick a world, or http://localhost:3000/cases/flagship?replay=4.

Useful commands:

```bash
uv run whydunit case open --world fixture:3inc     # investigate in the terminal
uv run whydunit evals run                          # the ten scenarios
uv run whydunit world create --incidents deploy_bug:webkit,ads_budget_cap --start 2026-09-14 --days 14
uv run pytest                                      # engine tests (81)
```

**Models.** With `NEBIUS_API_KEY` set (see `.env.example`), detectives use Nemotron on Token Factory: run
`uv run python scripts/discover_models.py --write` once to pin the model IDs, then `uv run python scripts/smoke_llm.py`.
Without a key, each detective runs its deterministic playbook and the board says so.

**The live world.** Acme Notes (`acme-demo`), the simulator, the watcher and the browser runner need GitHub, Vercel,
Neon, Stripe test mode, an S3 bucket and a Nebius AI Cloud project; `BLOCKERS.md` lists each step and
`docs/hosting.md` the judge deployment.

## Repository

| Path | What |
|---|---|
| `engine/agents` | the seven detectives, the lead, the fixer |
| `engine/analysis` | decomposition, segments, change detection, Shapley attribution, session heuristics |
| `engine/connectors` | the evidence ladder (APIs, warehouse, PyAirbyte, CSV, screen reading, fixture worlds) |
| `engine/runtime` | Token Factory client, validator, case event log, runner client, watcher, verifier |
| `engine/fixtures` | deterministic fixture worlds with planted incidents and exact ground truth |
| `simulator` | the live world simulator (GitHub Actions cron) |
| `runner` | Playwright runner for flows, keyframes and dashboard capture (Nebius Serverless Job) |
| `ui` | Next.js case board |
| `packages/snippet` | tracking + rrweb snippet |

The build plan lives in [PLAN.md](PLAN.md). MIT licensed.
