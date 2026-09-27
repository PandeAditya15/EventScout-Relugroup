# Decision log

Non-obvious choices made while building EventScout, in chronological order.

## 2026-09-25 — Project moved to a fresh folder, git ceremony dropped

- **Context:** initial session was pointed at an unrelated, already-submitted take-home repo.
- **Decision:** project lives at `/Users/adityasantoshpande/Relugroup/eventscout` instead. Per
  instruction, no git/GitHub workflow is enforced this time (no per-step commit handoff) — a plain
  local git repo exists (from `uv init`) but isn't part of the working loop.
- **Trade-off:** faster iteration, but no atomic-commit safety net; rely on periodic manual
  checkpoints instead.

## 2026-09-25 — `date_confidence` reuses the `confidence_level` enum

- **Context:** the schema spec (section 6) lists `dates.date_confidence` as a field but doesn't
  define its own enum, unlike audience/geographic_origin confidence which explicitly says
  high/medium/low.
- **Decision:** reuse `ConfidenceLevel` (high/medium/low) for `date_confidence` rather than
  inventing a separate enum, for consistency with the rest of the schema.
- **Trade-off:** slightly less semantically precise than a dedicated enum (e.g.
  confirmed/estimated/unknown), but avoids a one-off type for no stated reason.

## 2026-09-25 — `smoke-test` only lists models, doesn't also call generate_content

- **Context:** the brief asks for "one tiny call, then list the available models," but also says
  model IDs must never be hard-coded from memory and that the user picks them from the smoke-test
  output. A `generate_content` call needs a model ID upfront, which would force a guess.
- **Decision:** `smoke-test` makes exactly one live call — `client.models.list()` — which both
  proves the API key works and gives the user real model IDs to choose `DISCOVERY_MODEL`/
  `CHEAP_MODEL` from. No `generate_content` call is made until those are confirmed.
- **Trade-off:** doesn't independently verify that generation (not just listing) works with the
  key, but avoids hard-coding or auto-picking a model, which the brief explicitly forbids.

## 2026-09-27 — Real model IDs and pricing confirmed; brief's price estimate was wrong

- **Context:** `smoke-test` listed available models; user picked `gemini-2.5-flash`
  (`DISCOVERY_MODEL`) and `gemini-2.5-flash-lite` (`CHEAP_MODEL`). Pricing was then checked against
  https://ai.google.dev/gemini-api/docs/pricing (Paid tier / Standard), fetched twice to confirm.
- **Decision:** use the real confirmed rates: input $0.30/$0.10 per 1M tokens, output $2.50/$0.40
  per 1M tokens (Flash/Flash-Lite respectively), grounded search $35 per 1,000 requests after a
  shared 1,500/day free allowance. The brief's own estimate (~$14/1,000 grounded queries) was
  wrong — the real rate is $35/1,000 for these models.
- **Decision:** thinking tokens have no separate listed price — Google bills them at the output
  rate — so `cost.py` folds `thoughts_token_count` into the output token count rather than pricing
  it as a third bucket.
- **Trade-off:** the cost ledger prices every grounded query as paid, ignoring the shared
  1,500/day free allowance, since tracking a cross-model daily quota is out of scope for a
  per-run budget cap — this makes the estimate conservative (slightly over, never under).

## 2026-09-27 — Cache stores grounding metadata; budget cap checks before, not per-call-estimate

- **Context:** while writing the discover stage, found that `llm.py`'s cache only stored
  `{"text": ...}`. A cache hit on a grounded call would silently return text with no sources and
  no search-query count — evidence for events would vanish on every re-run after the first.
- **Decision:** the cache payload and `GenerateResult` now carry `sources` and
  `search_queries_executed` too, so a cache hit is indistinguishable from a fresh call to callers.
- **Context:** the brief also says `--max-cost-usd` should abort *before* any call whose
  conservative estimate would exceed the cap. Token counts aren't known until a response returns,
  so there's no way to estimate a specific upcoming call's cost in advance.
- **Decision:** `generate()` instead refuses to start a new priced call once the ledger's running
  total has already reached the cap (`ledger.check_budget(0.0)` before every live call; cache hits
  are exempt since they're free). This stops runaway spend at the granularity of "one call over,"
  not "the exact call that would tip it over."
- **Trade-off:** a single very expensive call could still land at or slightly past the cap before
  the *next* call is blocked, since nothing pre-estimates that one call's cost.
