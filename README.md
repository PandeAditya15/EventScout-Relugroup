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

A more detailed, file-by-file architecture reference with the same diagram is
also published [here](https://claude.ai/artifact/YDvGRtEccs1tKGK9nFBk35).

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

## Key decisions and trade-offs

The full rationale for every non-obvious choice is in
[docs/decisions.md](docs/decisions.md), written as they were made. The
highlights:

- **Model IDs and prices are never guessed.** `smoke-test` lists real
  available models; the first pick (`gemini-2.5-flash`) turned out to be
  deprecated for this API key despite being listed — only a real live call
  caught that. Pricing was fetched from the official page twice to confirm.
- **Every pipeline bug found in this project was found by running it live,
  not by unit tests.** Five separate bugs (wrong SDK method, a client
  garbage-collected mid-request, a deprecated model, the wrong thinking-config
  parameter, a cost ledger undercounting cached search queries) were all
  invisible to 60+ passing tests because those tests use a fake Gemini client.
  Two more (a stadium not matching its own city's name, German venue names
  failing an English-only location filter) were found by manually reading the
  output next to real event names, not by any automated check.
- **A feature was built, tested, and then reverted:** citing which specific
  source backs an attendance figure. It shipped clean, passed its tests, and
  then was found to be confidently citing the wrong page once checked against
  real data — reverted to an honest `null` rather than kept. See Limitations
  below for the deeper issue that revealed.
- **Total spend so far: ~$0.76 of the $5 project budget** (~15%), across every
  live test, bug-fix verification, and full regeneration in this build — not
  just the final run. A single fresh `--no-cache` run today costs roughly
  $0.05-0.30 depending on how much grounded search results vary.

## Engineering practices

### Process: small batches, one thing in flight, verify immediately

Work followed a Kanban-style continuous flow, not sprint-based Scrum: the milestone plan (M1-M7)
was broken into small, single-purpose steps, only one of which was ever in progress at a time
(a WIP limit of 1), and each step was verified — `ruff check`, `ruff format --check`, `pytest` —
*before* starting the next one, never batched up. No step estimation, no fixed-length iteration;
just small batch size and a hard rule against moving on with something unverified.

**Why test at every step, not just at the end:** two different kinds of tests catch two different
kinds of bugs, and both are necessary.

- **Fast unit tests** (66 of them, all using a fake Gemini client or a mocked HTTP transport) run
  in ~1 second, cost nothing, and catch *logic* regressions immediately — a budget-cap boundary
  condition, a date-overlap edge case, a cache key collision.
- **They cannot catch integration failures.** All 66 tests were green when the pipeline's first
  real live call hit three bugs back to back: a wrong SDK method name, a client object garbage
  collected mid-request, and a model ID that was deprecated despite being listed as available.
  None of that is visible to a test built on a fake client that always behaves exactly as expected.
- The practical rule this produced: run the real pipeline against the real API at the end of
  *every* milestone, not just once at the very end of the project. A bug caught the day it's
  introduced costs one fix; the same bug caught four milestones later means questioning whether
  everything built on top of the wrong assumption in between is also wrong. This is exactly what
  happened three separate times in this project (see `docs/decisions.md`) — each time, a live run
  surfaced something 60+ passing tests had missed, and each time it was fixed within the same
  session because nothing else had been built on top of it yet.

### Code organization: built to containerize and relocate without changes

The codebase has no hardcoded filesystem paths anywhere (verified: `grep` for absolute paths
across `src/` returns nothing) and no configuration baked into code — every secret and path comes
from either `os.environ` (`config.py`) or `Path(__file__).resolve()` (so `REPO_ROOT` is wherever
the code actually lives, not a fixed location). Dependencies are locked in `uv.lock` and declared
in `pyproject.toml`, so `uv sync` reproduces an identical environment anywhere.

The only state the pipeline writes is `cache/` and `data/interim/` — both already gitignored,
both safe to mount as a volume or discard entirely. That combination means a container image for
this project needs no code changes, just:

```dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install uv && uv sync
ENTRYPOINT ["uv", "run", "eventscout"]
```

(No Dockerfile exists in this repo yet — this is what one would look like, not a claim that
containerization has been done.) The same portability is *why* the architecture would tolerate
being "shifted" — moved to a different host, run in CI, or split into a scheduled job — without
touching application code, only environment variables.

### Why debugging stays simple

Every pipeline stage (`discover`, `extract`, `clean`, `enrich`, `export`) is a typed pure
function: given the same input, it produces the same output, with no hidden state. `clean.py` and
`export.py` take their HTTP client as a parameter instead of constructing one internally
(dependency injection), which is exactly why they could be covered by 40+ tests that never touch
the real network.

That structure turns "where's the bug" into a fast, mechanical question instead of a guessing
game: SDK/network mechanics can only be in `llm.py`; prompt or extraction-quality issues can only
be in `prompts.py`/`discover.py`/`extract.py`; output-shape issues can only be in `export.py`. In
practice, isolating the location-filter bug found in milestone 5 took one three-line Python
snippet calling `_matches_location()` directly in a REPL — not a full, several-cent pipeline run —
because the function being debugged had no dependencies to fake.

### Caching, CAP theorem, and load balancing

**Caching is real and already load-bearing here.** `cache.py` hashes `(model, prompt, config)`
with sha256 and serves an identical future call from disk for $0. This is the same role a
reverse-proxy or CDN cache plays in front of an expensive, rate-limited origin server — protect
the metered resource from redundant load. It's not theoretical: the same 6-category run that cost
$0.4173 live cost $0.0000 on a fully-cached repeat.

**CAP theorem and load balancers, honestly, don't apply to EventScout as built** — and it's worth
being precise about why, rather than reaching for them because they sound rigorous. CAP theorem
describes a trade-off for systems maintaining *shared, replicated* state across network-partitioned
*nodes*. EventScout is a single process, on one machine, with one writer and no replication — there
is no partition to have a trade-off about. Load balancers distribute *concurrent client requests*
across *multiple server instances*; EventScout has no server and nothing concurrent to distribute.
Claiming otherwise for a batch CLI tool would be exactly the kind of unearned-rigor a reviewer
should call out.

**Where they'd become real, tied to this project's own deferred pieces:**

- The optional Supabase/Postgres layer (milestone 6, not built) would be a genuine shared
  datastore, and Postgres is a CP system by design — under a partition, it refuses to serve a read
  or write it can't guarantee is consistent, rather than risk stale or conflicting data. Given that
  layer's actual design (`INSERT ... ON CONFLICT (id) DO UPDATE`, idempotent upserts keyed by a
  stable event ID), CP is the *correct* choice, not a compromise: two runs racing to upsert the
  same event should converge to one correct row, and a loud failure beats a silently duplicated or
  corrupted one.
- Load balancing would matter if EventScout became a *service* — an API handling concurrent
  requests for different city/month reports, or a fleet of workers processing many cities in
  parallel. At that point the local disk cache would need to become a shared cache (e.g. Redis) so
  N workers don't each pay for the same Gemini call, and a queue or load balancer would distribute
  jobs across them. None of that exists today because the brief asks for one city, one month, one
  process at a time — which is exactly what's built.

### Trade-offs

Beyond the ones in [Key decisions and trade-offs](#key-decisions-and-trade-offs) above:

- **A local disk cache over a distributed one.** Correct for the actual current scale (one
  process, one run at a time); upgrading to Redis is a scoped, well-understood change if
  concurrency is ever added, not a rewrite — the cache's interface (`get`/`put` by key) wouldn't
  need to change, only its storage backend.
- **Consistency over availability for the (deferred) database layer.** Choosing Postgres/Supabase
  already commits to CP; that's the right call for idempotent event upserts, but it's worth being
  able to say *why* rather than treating it as the only option.
- **Fixing bugs immediately over deferring cleanup.** Every bug found in live testing was fixed
  and re-verified in the same session it was found, rather than logged for later — at the cost of
  more, smaller live-testing iterations (and their small real cost) instead of one big batch at
  the end.

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

## Next steps

- Venue-calendar scrapers for major Munich venues (Messe München, Olympiapark,
  muenchen.de) as an additional, deterministic source alongside grounded search.
- Trade fair final reports (many publish attendance/visitor-origin figures
  after the event) as stronger evidence than a model's estimate.
- German-language discovery queries, since English-only prompts likely miss
  events that are well-documented but only in German.
- URL liveness checks on cited sources at export time, to catch dead links
  before they reach the deliverable.
- A small labelled eval set (a hand-checked list of real Munich October
  events) to measure precision/recall instead of relying on spot-checks.
- Scheduled refresh: re-running periodically as event listings firm up closer
  to the target month, rather than one snapshot.
- Finish Ticketmaster and Nominatim connectors (blocked on API keys), and the
  proper fix for source attribution precision (see Limitations) using
  Gemini's `grounding_supports` field.

## Status

Milestones 1-5 (partial) and 7: config, output schema, disk cache, cost
ledger, Gemini wrapper, and the full discover → extract → clean → enrich →
export pipeline all work end-to-end and have been run live against the real
API, not just tested with fakes. The OpenLigaDB connector adds a second,
deterministic source. Ticketmaster and Nominatim connectors are not built yet.

**Milestone 6 (optional Supabase persistence layer) was skipped by design** —
the brief marks it optional, and the JSON file remains the actual deliverable
either way; `--store none` (the only mode that exists) is the default.

Git history has been scanned for secrets (API keys, tokens, credential-bearing
URLs) — none found; `.env` has never been committed.

See [docs/decisions.md](docs/decisions.md) for the non-obvious choices made
along the way, including real bugs found only by running the pipeline live.
