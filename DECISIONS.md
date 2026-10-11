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
