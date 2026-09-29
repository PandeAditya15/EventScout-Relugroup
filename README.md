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

`TICKETMASTER_API_KEY` and `NOMINATIM_CONTACT_EMAIL` are optional — the
connectors that need them are skipped with a warning if unset. OpenLigaDB
needs no key at all.

## Running

```bash
uv run eventscout smoke-test        # confirm your API key works, list available models
uv run eventscout export-schema     # write schema/events.schema.json

uv run eventscout run --dry-run                    # preview planned calls, no API calls
uv run eventscout run                              # full run: all categories, all sources
uv run eventscout run --categories sports --sources openligadb --max-cost-usd 0.10
```

Key flags: `--city`, `--country`, `--month` (default Munich/DE/2026-10),
`--categories` (comma-separated, default all six), `--sources`
(comma-separated: `gemini`, `openligadb`; default both), `--max-cost-usd`
(default 2.0 — the run refuses a new paid call once spend reaches this),
`--no-cache`.

Output: `events_<mon>_<year>.json` at the repo root (e.g.
`events_oct_2026.json`), validated against `schema/events.schema.json`.

## Data sources

| Source | What it provides | Key needed | License / terms |
|---|---|---|---|
| Gemini grounded search | Discovery + extraction for all 6 categories | `GEMINI_API_KEY` | [Gemini API Terms](https://ai.google.dev/gemini-api/terms#grounding-with-google-search) |
| OpenLigaDB | FC Bayern München home matches (only Munich club confirmed in bl1/bl2/bl3) | none | [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/) |
| Ticketmaster Discovery | Concerts/sports/theatre listings | `TICKETMASTER_API_KEY` (optional) | not yet built — milestone 5, pending a coverage test |
| Nominatim (OpenStreetMap) | Geocoding venues missing coordinates | `NOMINATIM_CONTACT_EMAIL` (optional) | not yet built — milestone 5 |

Attributions actually present in a given run's output (`attributions` field)
depend on which sources contributed at least one event — see
`stages/export.py`.

## Status

Milestones 1-5 (partial): config, output schema, disk cache, cost ledger,
Gemini wrapper, and the full discover → extract → clean → enrich → export
pipeline all work end-to-end and have been run live against the real API, not
just tested with fakes. The OpenLigaDB connector adds a second, deterministic
source. Ticketmaster and Nominatim connectors are not built yet.

See [docs/decisions.md](docs/decisions.md) for the non-obvious choices made
along the way, including real bugs found only by running the pipeline live.

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```
