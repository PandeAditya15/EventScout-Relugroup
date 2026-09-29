# EventScout — Code reference

Purpose: a complete, file-by-file and function-by-function map of the codebase,
written to be read *alongside* the code — during a review, or when hunting a
bug. Each file has a **Check first if...** column: the specific things known
to be fragile or worth verifying here, based on what's actually gone wrong in
this project so far (see `docs/decisions.md` for the full incident history).

This is a reference, not a tutorial — see the [README](../README.md) for setup,
running, and the high-level pipeline diagram.

## Directory tree

```
src/eventscout/
├── cli.py                  # entry point; wires every stage together
├── config.py                # env, paths, model IDs, pricing table
├── models.py                 # every data shape: RawEvent, Event, enums
├── cache.py                   # disk cache (get/put by hash)
├── cost.py                    # CostLedger: pricing + budget cap
├── llm.py                      # the one place that calls the Gemini SDK
├── llm_schemas.py               # flat schemas for structured output
├── prompts.py                    # every prompt, as named constants
├── connectors/
│   └── openligadb.py              # Munich football fixtures (free, no key)
└── stages/
    ├── discover.py                 # grounded search, one call per category
    ├── extract.py                   # discovery text -> list[RawEvent]
    ├── clean.py                      # resolve URLs, filter, dedupe
    ├── enrich.py                      # audience + geographic-origin inference
    └── export.py                       # RawEvent -> final Event, write JSON

tests/                            # one file per module above, plus conftest.py
schema/events.schema.json         # generated from models.py, never hand-edited
docs/decisions.md                 # why, in chronological order
events_oct_2026.json              # the actual deliverable
```

**Who imports whom, roughly bottom-up:** `models.py` has no project
dependencies and is imported by almost everything. `cache.py` and `cost.py`
are independent of each other and of the SDK. `llm.py` imports both, plus the
real `google-genai` SDK's error types. `prompts.py` and `llm_schemas.py`
depend only on `models.py`. Each `stages/*.py` imports `llm.py` (except
`clean.py` and `export.py`, which have no LLM calls) plus whatever
`llm_schemas.py`/`prompts.py` it needs. `cli.py` is the only file that imports
every stage, plus the real `google.genai` client and `connectors/openligadb.py`.

---

## `src/eventscout/config.py`

Loads `.env`, computes filesystem paths, and holds the two things the project
brief says must never be guessed: model IDs and prices.

| Name | What it is | Check first if... |
|---|---|---|
| `REPO_ROOT` | `Path(__file__).resolve().parents[2]` | Paths break after moving the file — this assumes `config.py` stays exactly 2 directories under the repo root (`src/eventscout/config.py`). Moving the file breaks this silently (wrong root, not an error). |
| `CACHE_DIR`, `DATA_INTERIM_DIR`, `SCHEMA_DIR` | `REPO_ROOT`-relative, created on import (`mkdir(parents=True, exist_ok=True)`) | A run writes to an unexpected location — check these are what you expect before assuming a bug elsewhere. |
| `GEMINI_API_KEY`, `TICKETMASTER_API_KEY`, `NOMINATIM_CONTACT_EMAIL`, `DATABASE_URL` | Plain `os.environ.get(...)`, so `None` if unset | A key "isn't working" — confirm it's actually in `.env` and that `.env` is in the working directory `load_dotenv()` runs from. |
| `DISCOVERY_MODEL`, `CHEAP_MODEL` | Hardcoded strings, but only after being confirmed live via `smoke-test` | A live call 404s with "no longer available" — this is exactly how `gemini-2.5-flash` died; models get deprecated without warning, re-run `smoke-test` and re-pick. |
| `PRICING` | Nested dict, model ID -> `{input, output}` rates per 1M tokens, plus a flat grounded-search rate | Cost looks wrong — this table has **no entry for a model not in it** (`cost.py` silently returns $0 for an unpriced model, not an error). Adding a new model here requires updating this table by hand from the official pricing page. |
| `MUNICH_CLUB_STADIUMS` | `{club name: {stadium_name, capacity, capacity_source_url}}`, exact-string-keyed | OpenLigaDB events don't get a stadium — the key must exactly match `team1.teamName` from the API response (e.g. `"FC Bayern München"`, umlaut and all). A silent no-op if the string doesn't match. |

---

## `src/eventscout/models.py`

Every data shape in the project. No project imports — this is the leaf
dependency everything else builds on.

| Model | What it's for | Check first if... |
|---|---|---|
| `RawEvent` | The shared pipeline currency: one event from one source, before merge. Every field except `name` is optional. | A field is unexpectedly `None` downstream — check whether the *source* that produced this `RawEvent` (extract.py vs openligadb.py) ever populates that field at all. Not every field is set by every source. |
| `Event` (+ `EventDates`, `EventVenue`, `EventScale`, `EventAudience`, `EventGeographicOrigin`, `EventEvidence`, `EventDataQuality`) | The final, strict, schema-validated shape. Several fields here are **required** that are optional on `RawEvent` (`dates.start_date`, `scale.scale_tier`, `audience`, `geographic_origin`). | A `ValidationError` when building an `Event` — it's almost always `export.py` trying to construct one from a `RawEvent`/`EnrichedRawEvent` missing something required; see `export.py`'s table below. |
| Enums (`EventCategory`, `AttendanceBasis`, `ScaleTier`, `ConfidenceLevel`, `DiscoverySource`, `AudienceType`, `GeoScope`) | Fixed string vocabularies (`StrEnum`) | A category/enum value from Gemini doesn't validate — the LLM produced a value outside the enum; check the prompt's instructions and `llm_schemas.py`'s field type for that value. |
| `SourceRef` | `{url, title, publisher_domain, retrieved_at}` | `publisher_domain`/`retrieved_at` are `None` for most events — only `clean.py`'s URL resolution step sets `publisher_domain`; `retrieved_at` is never set anywhere in the current code (a real, minor gap — nothing populates it). |
| `EventScoutOutput` | Top-level wrapper: query, pipeline stats, attributions, stats, events | — |

---

## `src/eventscout/cache.py`

~30 lines. Disk cache: `sha256(model, prompt, config)` -> a JSON file in `cache/`.

| Function | What it does | Check first if... |
|---|---|---|
| `cache_key(model, prompt, config)` | Hashes the three inputs, `default=str` fallback for non-JSON-native objects in `config` (SDK objects like `types.Tool`) | Two calls that *should* be different hit the same cache entry, or vice versa — `default=str` means the hash depends on an object's `__repr__`/`__str__`; if the SDK ever changes how it reprs `types.Tool`/`types.ThinkingConfig`, old cache entries silently stop matching new calls (harmless — just an unnecessary cache miss, not wrong data). |
| `get(key)` / `put(key, value)` | Read/write a JSON file at `CACHE_DIR / f"{key}.json"` | A cache "isn't working" — check `CACHE_DIR` actually resolves to `cache/` at the repo root (see `config.py`), and that the process has write permission there. |

**No expiry, no invalidation beyond the hash itself changing.** If Gemini
starts returning different (better or worse) results for the exact same
prompt on a later date, the cache will keep serving the old response
indefinitely. This is deliberate (identical inputs = free reruns) but worth
knowing if "the data seems stale."

---

## `src/eventscout/cost.py`

Prices calls, enforces `--max-cost-usd`.

| Name | What it does | Check first if... |
|---|---|---|
| `CallRecord` | One row: stage, model, token counts, `search_queries`, `cache_hit`, `cost_usd` | — |
| `CostLedger.price_tokens(...)` | `input_tokens * input_rate + (output_tokens + thinking_tokens) * output_rate` | A cost looks too low — thinking tokens are folded into the output rate here (Gemini has no separate thinking price); if a future model *does* price thinking separately, this silently undercounts it. |
| `CostLedger.price_search_queries(...)` | Computes `count / 1000 * rate` | **Never actually called anywhere in the pipeline.** `llm.py`'s `generate()` tracks `search_queries` per call (for the stats field) but never adds their cost via this method — grounded-search-query billing is not reflected in `total_cost_usd` at all, only token costs are. At current scale (well under the free monthly quota) this hasn't mattered, but it's a real gap if usage ever grows past the free tier. |
| `CostLedger.check_budget(estimate)` | Raises `BudgetExceededError` if `total_cost_usd + estimate > max_cost_usd` | A run stops earlier than expected — called with `estimate=0.0` before every *live* call (see `llm.py`), meaning it blocks a new call once the running total is already over budget, not before the call that would tip it over. A single very expensive call can still land over the cap before the next one is blocked. |
| `CostLedger.summary()` | The end-of-run printed string | — |

---

## `src/eventscout/llm.py`

The single choke point for the Gemini SDK. If a bug involves the *mechanics*
of calling Gemini (not what's in the prompt), it's here.

| Name | What it does | Check first if... |
|---|---|---|
| `GeminiClient` (Protocol) | Structural type for "anything with `.generate_content(model=, contents=, config=)`" | Tests use a `FakeGeminiClient`; the real caller passes `genai.Client(...).models`, **not** `genai.Client(...)` directly — this exact mistake caused a live `AttributeError` once (see decisions.md). |
| `_is_retryable(exc)` / `_call_with_retry(...)` | Retries only on `APIError` with code in `{429, 500, 502, 503, 504}`, via `tenacity`, up to 4 attempts, exponential backoff | A call fails immediately with no retry — check the exception is actually a `google.genai.errors.APIError` with one of those codes; anything else (including a 400, or a non-SDK exception) is never retried. |
| `_extract_grounding(response)` | Pulls `Source` list + search-query count from `response.candidates[0].grounding_metadata` | Sources/query count come back empty for what should be a grounded call — check the response actually has `candidates` and `grounding_metadata` populated; a plain (non-tool) call always returns `([], 0)` here, which is correct, not a bug. |
| `generate(...)` | The full flow: cache check -> budget check -> retry -> parse usage -> price -> cache write | This is the one function every stage calls instead of the SDK directly. A cache hit reconstructs `GenerateResult` (including `sources`/`search_queries_executed`) from the stored JSON — if a bug makes cached results look different from fresh ones, compare the cache-hit branch against the fresh-call branch line by line; they were out of sync once before (search-query count wasn't carried through on cache hits — fixed, see decisions.md). |

**Field names used here** (`usage_metadata`, `prompt_token_count`,
`candidates_token_count`, `thoughts_token_count`, `.text`, `.candidates`,
`.grounding_metadata`, `.grounding_chunks`, `.web.uri`/`.web.title`,
`.web_search_queries`, `APIError.code`) were all verified against the
installed `google-genai` SDK source at the time of writing — if the SDK is
upgraded, re-check these against the new version before trusting them.

**Known, documented gap:** grounding responses also expose
`grounding_supports` (mapping specific text spans to specific source
indices), which this file does **not** capture. That's the root cause of the
source-attribution imprecision documented in the README's Limitations
section — if `extract.py`'s citations look wrong, this is why, and the fix
starts here.

---

## `src/eventscout/llm_schemas.py`

Small, flat Pydantic models used **only** as `response_schema` for structured
output — never returned to callers outside `extract.py`/`enrich.py`.

| Model | Used by | Check first if... |
|---|---|---|
| `ExtractedEvent` | `stages/extract.py` | A field silently doesn't make it into the final `RawEvent` — check it's both declared here *and* read in `extract.py`'s `_to_raw_event`; the two are kept in sync by hand, nothing enforces it. |
| `GeographicOriginItem` | `EnrichedEvent.geographic_origin_primary` | — |
| `EnrichedEvent` | `stages/enrich.py` | Enrichment for an event is missing or wrong — check `event_number` in the model response actually matches the 1-based position in the prompt's numbered list; a model that reorders or skips a number causes `enrich.py` to fall back to a low-confidence default for that event (not a crash, but silently worse data). |

---

## `src/eventscout/prompts.py`

Every prompt as a named string constant, plus `CATEGORY_FOCUS` (the one thing
that varies per discovery call).

| Check first if... |
|---|
| Discovery results seem biased toward big/English-language events — that's a documented limitation, not a bug, but the wording of `DISCOVERY_PROMPT_TEMPLATE` is the first thing to tune if trying to improve it. |
| Extraction drops events it shouldn't — `EXTRACTION_PROMPT_TEMPLATE` requires `source_numbers`; an event with none is discarded by design (`extract.py`), not a bug in the prompt necessarily. |
| A prompt change doesn't seem to take effect — remember prompts are part of the cache key (`llm.py`); a changed prompt naturally invalidates the cache for every call using it, which is expected, not a bug, but explains an unexpected live-call cost after an edit here. |

---

## `src/eventscout/connectors/openligadb.py`

Deterministic, free, no LLM. Returns `list[RawEvent]` directly.

| Function | What it does | Check first if... |
|---|---|---|
| `fetch_munich_home_matches(season, month, http_client, use_cache)` | Fetches the whole season's `bl1` fixtures once, filters to Munich clubs' home matches (`team1` = home, confirmed against real data, not documented by OpenLigaDB) overlapping `month` | Fewer/more matches than expected — the month filter compares `matchDateTimeUTC[:7]` (UTC) against `month`; a match within a few hours of midnight UTC on a month boundary could be assigned to the "wrong" month in local (Munich) time. A real, minor edge case, not yet hit in practice. |
| `_fetch_matches(url, ...)` | Caches the **entire season's raw response** under one key (by URL) | Data looks stale after OpenLigaDB updates a fixture (reschedule, postponement) — the cache never expires; delete the matching `cache/*.json` file or run with `--no-cache` to force a refresh. |
| `_to_raw_event(...)` | Builds the `RawEvent`, including the `venue_district="Munich"` hardcode | A Munich match gets dropped by `clean.py` as `wrong_location` — this exact bug happened once (Allianz Arena's name alone doesn't contain "Munich"); if it recurs, check this hardcode is still present and that `MUNICH_CLUB_STADIUMS` entries stay consistent with it. |

`MUNICH_CLUB_STADIUMS` (in `config.py`) currently has exactly one entry. Adding
a club requires confirming its stadium/capacity with a human, not guessing —
see the brief and `docs/decisions.md`.

---

## `src/eventscout/stages/discover.py`

One function: `discover_category(client, category, city, country_code, month, ledger, use_cache)`
→ `DiscoveryResult`. Builds the prompt, sets `tools=[google_search]` and
`thinking_level=LOW`, calls `generate()`.

**Check first if:** a discovery call costs much more than expected — this is
the only stage using the expensive `DISCOVERY_MODEL` (9x the output price of
`CHEAP_MODEL`); an unconfigured or higher thinking level here is exactly what
caused a $0.42 run once (see decisions.md). Confirm `thinking_config` is still
set to `LOW`.

---

## `src/eventscout/stages/extract.py`

`extract_events(client, text, sources, category, ledger, use_cache)` →
`list[RawEvent]`.

| Function | What it does | Check first if... |
|---|---|---|
| `extract_events(...)` | No-ops (`return []`) if `text` or `sources` is empty; otherwise calls `generate()` with `response_schema=list[ExtractedEvent]` and drops any result with empty `source_numbers` | Zero events from a category that clearly has results in the discovery text — check `discovery.sources` wasn't empty (grounding sometimes returns text with no citable sources), which short-circuits extraction entirely before any model call. |
| `_parse_extracted_events(text)` | `json.loads`, then validates each item; returns `[]` on a `JSONDecodeError` | An extraction "silently fails" — a malformed model response never raises, it just produces zero events for that call. Check the raw cached response file (`cache/<hash>.json`) for that call to see the actual model output. |
| `_to_raw_event(...)` | Resolves `source_numbers` (1-based) into real `SourceRef`s from the `sources` list; **`attendance_source_url` is always left `None`** | An attendance figure has no source URL — this is deliberate, not a bug (see decisions.md: a prior attempt to populate this field produced confidently wrong citations and was reverted). |

---

## `src/eventscout/stages/clean.py`

Pure Python, five steps run in a fixed order inside `clean_events(...)`. No
LLM calls; the only network use is `httpx` for URL resolution, injected as a
parameter (not constructed here) — this is why 40+ tests cover this file
without touching the real network.

| Function | What it does | Check first if... |
|---|---|---|
| `resolve_source_urls` / `_resolve_one` / `_resolve_url` | Follows redirects (`follow_redirects=True`, 5s timeout), caches by URL hash; keeps the original URL on any `httpx.HTTPError` | A source URL still points at `vertexaisearch.cloud.google.com/redirect/...` in the final output — either resolution failed silently (check for a network/timeout issue) or this event's URL was never routed through `_resolve_url` at all (check `clean_events`'s loop covers the field in question — this exact gap existed once for `attendance_source_url` before both fields were unified under `_resolve_url`). |
| `filter_by_month_and_location` / `_overlaps_month` / `_matches_location` | Keeps by default; only drops on **positive evidence** of wrong month or city | An event you expected to see is missing — check `dropped_by_reason` in the run output first. `_matches_location` uses `rapidfuzz.fuzz.partial_ratio` (threshold 60), not exact substring — it fixes German/English city-name variants close enough lexically (München/Munich) but **not** ones that are simply different words (Cologne/Köln would still fail). If a real event is missing and its venue is in a differently-worded local language, this is the first place to check. |
| `normalize_name` | Lowercases, strips years/ordinals/punctuation, folds diacritics to ASCII | Two names that "should" match don't — this does **not** translate between languages (a German and English title for the same event stay different strings); it only handles spelling/accent/edition-number variants. |
| `dedupe_events` / `_find_match` / `_dates_overlap` / `_merge_events` | O(n²) pairwise comparison; merges when name similarity ≥ 85 (`fuzz.token_sort_ratio`) **and** dates overlap (or either side's date is unknown) | Two events wrongly merged, or two duplicates left separate — check both the name-similarity score and the date-overlap condition; a missing date on either side makes the date check pass automatically (by design, to not block a likely match on missing data — but it can also let a false match through). `_merge_events` prefers whichever event was inserted into the list *first* for every ambiguous field — this is **not** the brief's stated "prefer connector data over LLM-extracted data" policy; that preference isn't implemented, since no field-level connector-vs-LLM logic exists here yet. Also: O(n²) is fine at tens of events per run; would need revisiting if event counts grow by an order of magnitude. |
| `drop_unsourced` | Drops any event with an empty `sources` list | An event that "should" have sources is gone — check whether `extract.py`'s `_to_raw_event` actually resolved any of its `source_numbers` into a valid index; an event can pass extraction's own filter (non-empty `source_numbers`) but still end up with zero real `SourceRef`s if every number was out of range. |

---

## `src/eventscout/stages/enrich.py`

`enrich_events(client, events, ledger, use_cache)` → `list[EnrichedRawEvent]`,
batching `BATCH_SIZE = 5` events per call.

| Function | What it does | Check first if... |
|---|---|---|
| `enrich_events` / `_enrich_batch` | Numbers events 1..N within a batch (not across the whole run), sends one `generate()` call per batch | Audience/origin looks wrong for a specific event — first check `_describe(event)`'s output for that event; enrichment only ever sees this short summary, not the full `RawEvent`, so anything not included there (e.g. `venue_address`, `organizer`) can't influence the inference. |
| `_parse_enriched_events` | Same "fail soft" pattern as extraction: malformed JSON → empty dict, not a raised exception | A whole batch's events all show `confidence: "low"` with the same fallback rationale — the batch's model response failed to parse; check that batch's cached response file. |
| Missing `event_number` in response | Falls back per-event, not per-batch | One event in a batch of 5 has the fallback while the other 4 look normal — the model skipped or misnumbered just that one; not a systemic issue. |

---

## `src/eventscout/stages/export.py`

Pure Python. `build_event(enriched)` → `Event | None`; `build_output(...)` →
`EventScoutOutput`. This is where every "required in `Event` but optional in
`RawEvent`" gap gets resolved one way or another.

| Function | What it does | Check first if... |
|---|---|---|
| `build_event` | Returns `None` (dropped) if `raw.start_date is None` — the only hard requirement | An event count is lower than expected at the very last stage — check `stats.dropped_by_reason["no_start_date"]` in the output; this is the one place an otherwise-valid, sourced event can still disappear. |
| `_make_id` | `slug(name) + "-" + start_date + "-" + sha256(name\|date\|venue)[:6]` | Two different events get the same `id` — extremely unlikely (would need identical name, date, *and* venue) but not cryptographically guaranteed; check the three fingerprint inputs if it ever happens. |
| `_infer_scale_tier` | Thresholds: <5k local, <20k regional, <100k national, ≥100k international; unknown attendance → `local` | A `scale_tier` looks off for a known-huge event with no attendance figure — this defaults to the most conservative tier when attendance is unknown, by design (not a guess upward). |
| `_classify_fields` | `fact_fields` always includes `name`, `dates`; conditionally adds `venue`/`organizer`/`url`/`scale.attendance` if present; `inferred_fields` is always `["audience", "geographic_origin"]` | `fact_fields` looks incomplete for an event with real data in a field not listed here (e.g. `ticketing`, `is_outdoor`) — this function only checks the handful of fields it was written to check; it is not derived automatically from which fields are non-null. |
| `_lowest_confidence` | `overall_confidence` = the least confident of (date, audience, geo) | `overall_confidence` seems too pessimistic — by design, one low-confidence input drags the whole event down; this is not an average. |
| `ATTRIBUTION_BY_SOURCE` | Maps `DiscoverySource` → `Attribution`, only included in output if that source actually appears in `sources_used` | A new connector's attribution never shows up — check it's been added to this dict; nothing does this automatically from `models.py`'s `DiscoverySource` enum. |
| `build_output` | Aggregates stats via `Counter`; merges `dropped_by_reason` from clean.py with `no_start_date` from this stage | `stats.event_count` doesn't match what you expect — cross-check `dropped_by_reason` (clean-stage drops) plus any `no_start_date` count; the two together should account for the gap from raw discovery counts. |

---

## `src/eventscout/cli.py`

The only file that wires every stage together, and the only place that
constructs the real `genai.Client`.

| Function | What it does | Check first if... |
|---|---|---|
| `smoke_test` | One live call: `client.models.list()` | Used to confirm a key/model, never to pick a model automatically — no code here selects a model; a human always does, per the brief. |
| `_parse_categories` / `_parse_sources` | `_parse_sources` raises `typer.BadParameter` for anything not in `{"gemini", "openligadb"}` | `--sources ticketmaster` or similar errors out cleanly — this is intentional; that connector doesn't exist yet, so it's not silently ignored. |
| `_bundesliga_season_for_month` | `year if month_num >= 8 else year - 1` | An OpenLigaDB query returns the wrong season — this is a judgment call about when a Bundesliga season starts (August), not a fact verified from OpenLigaDB itself; double-check against `docs/decisions.md` if fixtures look off around a season boundary. |
| `run` | The full orchestration: OpenLigaDB (if selected) → discover/extract loop (if `gemini` selected) → clean → enrich → export → write both `data/interim/<run_id>/output.json` and the root `events_<mon>_<year>.json` | **Two places silently swallow `BudgetExceededError`** and continue with partial data: the discover/extract loop (prints "Stopped", proceeds to clean whatever was collected) and the enrich call (prints "Stopped during enrichment", proceeds with `enriched = []` — meaning **zero** final events even if cleaning succeeded). If a run ends with an empty or truncated output and a cost near the cap, check for this message in the run's console output before assuming a different bug. |
| Client lifetime | `client = genai.Client(...)`, then `models_client = client.models`, both kept in scope | If refactoring this function, keep `client` referenced for the whole call — discarding it right after taking `.models` let the underlying HTTP connection get garbage-collected mid-request once (a real, reproduced bug; see decisions.md). |

---

## Tests (`tests/`)

66 tests total, all synthetic data or a fake/mocked transport — **zero tests
touch the real network or spend money.**

| File | Covers | Tests |
|---|---|---|
| `conftest.py` | Shared `FakeGeminiClient`, response builders, `isolated_cache` (autouse — every test gets a temp cache dir) | — |
| `test_models.py` | Schema validation against a synthetic fixture event | 5 |
| `test_cache.py` | Key stability, get/put round-trip | 4 |
| `test_cost.py` | Pricing math, budget-cap enforcement | 6 |
| `test_llm.py` | Cache hit/miss, retry-on-429/no-retry-on-400, grounding metadata surviving a cache hit, budget refusal | 7 |
| `test_discover.py` | Prompt construction, result shape | 2 |
| `test_extract.py` | JSON parsing (incl. one **real, trimmed** Gemini response fixture), source-number resolution, malformed-JSON fallback | 6 |
| `test_clean.py` | URL resolution (mocked redirects), month/location filtering (incl. the German-venue-name case), name normalization, dedupe, end-to-end | 16 |
| `test_enrich.py` | Batch numbering, fallback on missing/malformed results | 5 |
| `test_export.py` | Event assembly, scale-tier thresholds, confidence roll-up, attribution inclusion logic | 7 |
| `test_openligadb.py` | Real (trimmed) fixture response, home/away filtering, capacity attendance, request-failure fallback | 4 |
| `test_cli.py` | `export-schema` output validity, `--dry-run`/missing-key exits (never `smoke-test` or `run` live) | 4 |

**What these tests structurally cannot catch:** anything about the real SDK's
method names, object lifecycle, or actual API behavior — every bug found by a
live call (see decisions.md) passed all relevant tests beforehand, because
`FakeGeminiClient` always behaves exactly as expected by construction.

---

## Other files

| Path | What it is | Check first if... |
|---|---|---|
| `schema/events.schema.json` | Generated by `eventscout export-schema` from `EventScoutOutput.model_json_schema()` | It looks out of date — it's never hand-edited; regenerate it after any `models.py` change. |
| `events_oct_2026.json` | The actual deliverable, produced by `eventscout run` | Doesn't match current code — it's a snapshot from whenever it was last generated, not auto-regenerated; re-run to refresh it. |
| `docs/decisions.md` | Chronological log of every non-obvious choice and every bug found, with root cause | The "why" behind anything that looks like a workaround, hardcode, or unusual threshold in the code above — nearly everything flagged in this document has a longer writeup there. |
| `pyproject.toml` / `uv.lock` | Dependency declarations / lockfile | `uv sync` behaves unexpectedly — `uv.lock` pins exact versions; delete and regenerate only if intentionally upgrading. |
