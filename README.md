# EventScout

Finds real-world events in a given city and month that could attract meaningful
attendance, and outputs strict, schema-validated JSON: event details, who's
likely to attend and where they're likely to come from, with the sources behind
every claim.

## Approach

Two source types feed one shared pipeline. Gemini's grounded search discovers
and extracts events per category; OpenLigaDB deterministically returns Munich
football fixtures. Both produce the same intermediate shape (`RawEvent`), so
everything downstream — cleaning, enrichment, export — doesn't care which
source an event came from.

```
     city / country / month
                │
                ▼
   ┌─────────────────────────┐
   │ discover (per category) │  gemini-3.5-flash + google_search
   └─────────────────────────┘
                │  text + sources
                ▼
   ┌─────────────────────────┐
   │         extract         │  gemini-3.5-flash-lite, structured JSON
   └─────────────────────────┘
                │  list[RawEvent]          ◀── OpenLigaDB also joins here (free, no key)
                ▼
   ┌─────────────────────────┐
   │          clean          │  resolve URLs, filter month/city, dedupe
   └─────────────────────────┘
                │  deduped RawEvent
                ▼
   ┌─────────────────────────┐
   │         enrich          │  gemini-3.5-flash-lite, batches of 5
   └─────────────────────────┘
                │  EnrichedRawEvent
                ▼
   ┌─────────────────────────┐
   │         export          │  build final Event, write JSON
   └─────────────────────────┘
                │
                ▼
     events_oct_2026.json (schema-valid)

Every discover/extract/enrich call goes through one wrapper (llm.py):
cache lookup -> budget check -> retry (tenacity, on 429/5xx) -> cost record
```

Full file-by-file breakdown: [docs/code_reference.md](docs/code_reference.md).
A visual version of this diagram is also published
[here](https://claude.ai/artifact/YDvGRtEccs1tKGK9nFBk35).

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
# 1. Verify the code (no network, no cost)
uv run ruff check . && uv run ruff format --check . && uv run pytest -q

# 2. Confirm your API key works (one tiny live call)
uv run eventscout smoke-test

# 3. Preview a run before spending anything
uv run eventscout run --dry-run

# 4. The real end-to-end run (hard cost cap; cached calls are free)
uv run eventscout run --max-cost-usd 0.30

# 5. Inspect the result
uv run python -c "
import json
data = json.load(open('events_oct_2026.json'))
print('events:', len(data['events']))
print('stats:', data['stats'])
"
```

Cheap/fast variations: `--categories sports --sources openligadb` (one
category, one source) or `--no-cache` (force a fully live run). `uv run
eventscout export-schema` regenerates `schema/events.schema.json`.

Key flags: `--city`, `--country`, `--month` (default Munich/DE/2026-10),
`--categories`, `--sources` (`gemini`, `openligadb`; default both),
`--max-cost-usd` (default 2.0 — refuses a new paid call past this), `--no-cache`.

Output: `events_<mon>_<year>.json` at the repo root, validated against
`schema/events.schema.json`.

## Data sources

| Source | What it provides | Key needed | License / terms |
|---|---|---|---|
| Gemini grounded search | Discovery + extraction for all 6 categories | `GEMINI_API_KEY` | [Gemini API Terms](https://ai.google.dev/gemini-api/terms#grounding-with-google-search) |
| OpenLigaDB | FC Bayern München home matches (only Munich club confirmed in bl1/bl2/bl3) | none | [ODbL](https://opendatacommons.org/licenses/odbl/1-0/) |
| Ticketmaster Discovery | Concerts/sports/theatre listings | `TICKETMASTER_API_KEY` (optional) | not built yet — pending a coverage test |
| Nominatim (OpenStreetMap) | Geocoding venues missing coordinates | `NOMINATIM_CONTACT_EMAIL` (optional) | not built yet |

Attributions in a run's output depend on which sources actually contributed
an event — see `stages/export.py`.

## Key decisions and trade-offs

Full rationale for every non-obvious choice: [docs/decisions.md](docs/decisions.md).
Highlights:

- **Model IDs and prices are never guessed.** The first model picked
  (`gemini-2.5-flash`) turned out deprecated despite being listed — only a
  real call caught that.
- **Every pipeline bug in this project was found by running it live, not by
  unit tests** — five integration bugs and two data-quality bugs were all
  invisible to 60+ passing fake-client tests.
- **A feature (attendance source citation) was built, tested, shipped, then
  reverted** after being found to confidently cite the wrong page against
  real data — an honest `null` beats a wrong-looking citation.
- **Local disk cache, not a distributed one** — correct for one process at a
  time; a scoped upgrade (not a rewrite) if concurrency is ever added.
- **Milestone 6 (Supabase) skipped by design** (optional per the brief); git
  history has been scanned and has no secrets.
- **Total spend: ~$0.76 of the $5 budget (~15%)**, across every live test and
  fix in this build, not just the final run.

## Limitations

- **Per-event source attribution is approximate, not precise.** Gemini's
  grounded search reports which pages it used overall, not which sentence
  came from which page — so extraction can attach a real, valid URL to the
  wrong event once one call covers many events sharing a large source pool.
  A proper fix needs Gemini's `grounding_supports` field, not yet captured.
- **LLM recall gaps** — smaller or recently-announced events are more likely
  missed than major ones.
- **Audience/geographic-origin are inferences**, not measurements — always
  labeled as such with a confidence level and rationale.
- **Bias towards English-language and large events.**
- **Attendance figures are inconsistently available**, and `reported` vs
  `estimated` is itself model-judged for non-connector sources.
- **Ticketmaster coverage for Munich is unconfirmed** — not built yet.

## Next steps

- Venue-calendar scrapers (Messe München, Olympiapark, muenchen.de) as an
  additional deterministic source.
- Trade fair final reports as stronger attendance/origin evidence than a
  model estimate.
- German-language discovery queries.
- URL liveness checks on cited sources at export time.
- A small labelled eval set to measure precision/recall.
- Scheduled refresh instead of one snapshot.
- Finish Ticketmaster/Nominatim, and fix source-attribution precision via
  `grounding_supports`.
