# Feedback log — Nebius Token Factory, Nebius AI Cloud, NVIDIA Nemotron, Tavily

Logged as it happens; this becomes the submission's feedback section. Each entry: what we tried, what
happened, and a suggestion.

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
