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
