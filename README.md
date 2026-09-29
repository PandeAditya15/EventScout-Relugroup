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

## Running the pipeline end to end

**1. Verify the code (no network, no cost):**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

**2. Confirm your API key works (one tiny live call):**

```bash
uv run eventscout smoke-test        # lists the Gemini models your key can use
```

**3. Preview a run before spending anything:**

```bash
uv run eventscout run --dry-run     # prints planned calls, makes zero API calls
```

**4. The real end-to-end run:**

```bash
uv run eventscout run --max-cost-usd 0.30
```

Runs discover → extract → clean → enrich → export across all 6 categories and
both sources. `--max-cost-usd` is a hard cap — the run refuses to start a new
paid call once spend reaches it. Identical calls are cached, so re-running
after the first time is usually close to $0.

To force a fully live run (bypass the cache and see real behavior/cost again):

```bash
uv run eventscout run --max-cost-usd 0.50 --no-cache
```

**5. Look at the result:**

```bash
uv run python -c "
import json
data = json.load(open('events_oct_2026.json'))
print('events:', len(data['events']))
print('stats:', data['stats'])
for e in data['events']:
    print('-', e['name'], '|', e['category'])
"
```

**Useful variations while testing:**

```bash
# One category, one source — cheap and fast for spot-checking
uv run eventscout run --categories sports --sources openligadb --max-cost-usd 0.10

# A genuinely fresh city/month, nothing cached
uv run eventscout run --city Hamburg --country DE --month 2026-11 --sources gemini --max-cost-usd 0.30
```

**Other commands:**

```bash
uv run eventscout export-schema     # (re)write schema/events.schema.json from the live models
```

Key flags: `--city`, `--country`, `--month` (default Munich/DE/2026-10),
`--categories` (comma-separated, default all six), `--sources`
(comma-separated: `gemini`, `openligadb`; default both), `--max-cost-usd`
(default 2.0), `--no-cache`.

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

## Limitations

- **Per-event source attribution is approximate, not precise.** Gemini's grounded search reports
  which pages it used overall for a response, but not which specific sentence came from which
  page. When one discovery call covers several events sharing a large pool of sources (common for
  categories like trade fairs), the extraction step can attach a real, valid URL to the wrong
  event. The events themselves are real; the specific citation on any one event may not be the
  exact page that stated that specific fact. See `docs/decisions.md` (2026-09-29 entries) for the
  full investigation. A proper fix would use Gemini's `grounding_supports` field to preserve the
  real text-to-source mapping, which `discover.py` doesn't currently capture.
- **LLM recall gaps.** Grounded search finds what's indexed and prominent; smaller or
  recently-announced events are more likely to be missed than major ones.
- **Audience and geographic-origin fields are inferences**, not measurements — always labeled as
  such, with a confidence level and rationale, but ultimately the model's estimate from event
  type/scale, not survey data.
- **Bias towards English-language and large events.** Discovery prompts and result ranking
  naturally favor content that ranks well in English-language search.
- **Attendance figures are inconsistently available** and, when present, of mixed reliability
  (`reported` vs `estimated` is itself model-judged for non-connector sources).
- **Ticketmaster coverage is unconfirmed** for Munich — that connector isn't built yet (see Data
  sources above).

## Status

Milestones 1-5 (partial): config, output schema, disk cache, cost ledger,
Gemini wrapper, and the full discover → extract → clean → enrich → export
pipeline all work end-to-end and have been run live against the real API, not
just tested with fakes. The OpenLigaDB connector adds a second, deterministic
source. Ticketmaster and Nominatim connectors are not built yet.

See [docs/decisions.md](docs/decisions.md) for the non-obvious choices made
along the way, including real bugs found only by running the pipeline live.
