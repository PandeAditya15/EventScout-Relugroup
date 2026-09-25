# EventScout

Finds real-world events in a given city and month that could attract meaningful
attendance, and outputs strict, schema-validated JSON: event details, who's
likely to attend and where they're likely to come from, with the sources behind
every claim.

## Setup

```bash
uv sync
cp .env.example .env   # fill in GEMINI_API_KEY (required); other keys optional
```

## Running

```bash
uv run eventscout smoke-test        # confirm your API key works, list available models
uv run eventscout export-schema     # write schema/events.schema.json
```

`eventscout run --city Munich --country DE --month 2026-10` (the main pipeline
command) lands in milestone 2.

## Status

Foundation only so far: config, the output/RawEvent schema, disk cache, cost
ledger, and the Gemini call wrapper, each with tests. See
[docs/decisions.md](docs/decisions.md) for non-obvious choices made along the way.

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```
