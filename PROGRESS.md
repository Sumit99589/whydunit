# Progress

Current stage: **Stage 1 — Repo scaffold, model client, smoke tests**

## Stage 1
- [x] Monorepo layout (engine, ui, packages/snippet, runner, config, docs, scripts, simulator, tests)
- [x] `engine/runtime/llm.py`: role-based Nemotron client (nano/super/ultra/omni from `config/models.yaml`),
      reasoning switch, retries with backoff, timeouts, disk cache, cost meter with per-case budget
- [x] `scripts/discover_models.py` (GET /v1/models → suggested and pinned `models.yaml`)
- [x] `scripts/smoke_llm.py` (text on nano/super/ultra, tool call on nano, image on omni)
- [x] Unit tests for the client (fake backend): 8 passing
- [x] Next.js UI scaffold (Next 16.4, Tailwind 4); `pnpm typecheck` and `pnpm lint` pass locally
- [x] CI workflow (ruff, ruff format, pytest, UI typecheck and lint)
- [x] PROGRESS / DECISIONS / BLOCKERS / FEEDBACK started
- [ ] **Smoke script against Token Factory**: waiting on `NEBIUS_API_KEY` (BLOCKERS B1)
- [ ] **Model IDs verified** via discover_models (B1)
- [ ] CI green on GitHub

## Last verification
```
uv run pytest -q            → 8 passed
uv run ruff check .         → clean
pnpm typecheck && pnpm lint → clean
```
