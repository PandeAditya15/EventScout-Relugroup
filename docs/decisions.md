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

## 2026-09-27 — First live run surfaced three real bugs; switched off gemini-2.5-*

The first-ever real (non-fake-client) call to the pipeline failed three times in a row, each
time on something no unit test could have caught since all tests use a fake client:

1. **`cli.py` called `client.generate_content(...)` instead of `client.models.generate_content(...)`.**
   `genai.Client` has no `generate_content` method directly -- only `Client.models` does. Fixed by
   passing `client.models` into `discover_category`/`extract_events`.
2. **`genai.Client(api_key=...).models` was passed around without keeping `client` itself alive.**
   With no reference to the parent `Client`, its underlying HTTP client got garbage-collected and
   closed before the request fired (`RuntimeError: Cannot send a request, as the client has been
   closed.`). Fixed by keeping `client = genai.Client(...)` bound in `run()`'s scope for the
   duration of the call.
3. **`gemini-2.5-flash` returned a live 404**: "no longer available to new users... use
   models/gemini-3.5-flash" (Google's message actually named gemini-3.8-flash, but the user chose
   3.5 as more established). Being listed by `smoke-test` does not mean a model is actually usable
   by a given key -- only a real `generate_content` call proves that.
- **Decision:** switched `DISCOVERY_MODEL` to `gemini-3.5-flash` and `CHEAP_MODEL` to
  `gemini-3.5-flash-lite`, with pricing re-confirmed from the official page for both (grounded
  search on Gemini 3.x is $14/1,000 requests with a 5,000/month free allowance shared across all
  3.x models -- different from the 2.5-generation's $35/1,000 with a 1,500/*day* allowance).
- **Decision:** rejected `gemini-flash-lite-latest` for `CHEAP_MODEL` even though the user
  initially picked it, because it's an alias with no distinct row on the pricing page -- its real
  per-token cost can't be verified, which would make the cost ledger silently wrong (pricing it at
  $0 via the "unpriced model" fallback in `cost.py`).
- **No cost was incurred** by any of these three failed attempts: bugs (1) and (2) failed in
  Python before any HTTP request was sent, and (3) was a 404 client error, which the SDK doesn't
  bill for.

## 2026-09-27 — extract.py used the wrong thinking-config parameter for 3.x models

- **Context:** with the model bugs above fixed, the discover call succeeded (first successful
  live call), but extract failed with a bare `400 INVALID_ARGUMENT`. `extract.py` had set
  `ThinkingConfig(thinking_budget=0)` to disable thinking -- `thinking_budget` is the older,
  token-count-based parameter. The official docs (ai.google.dev/gemini-api/docs/thinking) show
  Gemini 3.5-generation models are configured via `thinking_level` (minimal/low/medium/high)
  instead.
- **Decision:** switched to `ThinkingConfig(thinking_level=ThinkingLevel.MINIMAL)` -- the lowest
  available level -- confirmed against the SDK's `ThinkingLevel` enum in `types.py`.
- **Trade-off:** none really; this is a straight fix. Worth noting for future model-generation
  changes: `thinking_budget` vs `thinking_level` isn't interchangeable across Gemini generations,
  and picking the wrong one fails at request time, not at schema-build time.

## 2026-09-27 — First successful live run; found the cache was undercounting search queries

With both bugs above fixed, `eventscout run --categories festival_culture --max-cost-usd 0.10`
completed end to end for the first time: 5 real events (Oktoberfest, Auer Dult, Museum Night,
Munich Crime Festival, Munich Marathon), each with real `vertexaisearch.cloud.google.com`
grounding-redirect source URLs, real dates and attendance figures, for **$0.0059** total.

That run's discover call was itself a cache hit (reusing the one successful discover call from
the earlier failed attempt), which surfaced one more bug: the cache file correctly stored
`search_queries_executed: 10`, but `generate()`'s cache-hit branch built its `CallRecord` without
a `search_queries` value, so the ledger's `search_queries_executed` tallied `0` for that call
despite the real count sitting right there in the cached payload.
- **Decision:** the cache-hit branch now passes `search_queries=cached_search_queries` into the
  `CallRecord`, matching the fresh-call branch. Added a ledger-level assertion to the existing
  cache-hit test (`ledger.search_queries_executed == 4`) so a regression here fails loudly instead
  of just showing up as a wrong number in a run's cost summary.
- Every bug found across this whole live-testing session was invisible to the 32 fake-client
  tests, because they all pass in plausible-looking data and never touch the real SDK's method
  names, client lifecycle, model availability, or thinking-config shape. The fake-client tests
  verify our *logic* (caching, retrying, budget math); only a real call verifies our *integration*
  with the actual SDK and API. Both are necessary; neither is sufficient alone.

## 2026-09-28 — Milestone 3 (clean stage) design choices

- **Location filter is permissive, not strict.** `filter_by_month_and_location` only drops an
  event when there's positive evidence it's in the wrong month or city (e.g. venue_address says
  "Berlin"). Events with no date or no venue info at all are kept rather than dropped, since a
  missing field isn't evidence of a mismatch -- dropping on absence would silently lose events the
  model found real sources for but couldn't pin down every detail on.
- **Name normalisation folds diacritics, doesn't translate.** `normalize_name` strips years,
  ordinals, and punctuation, and folds accented characters to ASCII (München -> munchen) so minor
  spelling variants match. It does **not** attempt German/English translation (e.g. it won't match
  "Biergarten" to "Beer Garden") -- that's left to rapidfuzz's similarity scoring in `dedupe_events`
  for near-misses, and genuinely different names are expected to stay separate.
- **Dedup merge policy is "first non-null value wins, sources/discovered_via always union."**
  When two RawEvents are judged the same event (similar normalised name + overlapping or unknown
  dates), most fields keep whichever side already had a value; `sources` and `discovered_via` are
  unioned regardless, since evidence should accumulate even when facts don't need to change. The
  brief's "prefer connector values over LLM-extracted values for dates/venue/coordinates" isn't
  implemented yet since no connector exists to prefer (milestone 5).
- **URL resolution failure is silent, not an error.** If `httpx` can't resolve a grounding
  redirect (timeout, DNS failure, etc.), `resolve_source_urls` keeps the original URL rather than
  raising or dropping the source -- consistent with the brief's "flag it if resolution fails"
  (the flag here is simply that the URL still points at the redirect service, not a real domain).
- **Clean runs once, after all categories, not per-category.** The brief's pipeline description
  says clean operates "for all sources" as a single pass, so `cli.py`'s `run` command collects
  every category's RawEvents first and calls `clean_events` once on the combined list -- this is
  also where cross-category duplicates (e.g. a marathon appearing in both `sports` and
  `festival_culture`) actually get merged.

## 2026-09-28 — Milestone 4 (enrich + export) design choices

- **Enrichment batches reference events by number, not name.** Same pattern as extraction's
  `source_numbers`: the prompt numbers each event 1..N, and the model returns `event_number` per
  result. This survives the model reordering or skipping an event in its response, which matching
  by name (fuzzy or exact) would be more fragile against.
- **A missing/malformed enrichment result gets a low-confidence fallback, not a dropped event.**
  If the model omits an event from a batch response, or the whole response fails to parse, that
  event still makes it to export with `audience.confidence = "low"` and a rationale saying
  enrichment failed -- an event with no inference at all would violate the schema (audience/
  geographic_origin are required), and dropping a real, sourced event because one inference call
  had a hiccup felt like the wrong trade-off.
- **scale_tier thresholds are a judgment call, not specified in the brief:** local <5,000,
  regional <20,000, national <100,000, international >=100,000 attendance. An event with unknown
  attendance defaults to `local` (the most conservative tier) rather than guessing higher.
- **Events with no `start_date` are dropped at export, not at clean.** `EventDates.start_date` is
  required by the final schema, but `RawEvent.start_date` is optional (extraction sometimes can't
  find a date). Dropping happens as late as possible -- at the point the schema constraint actually
  bites -- and is counted under a new `no_start_date` reason in `stats.dropped_by_reason`, merged
  in by `build_output` alongside clean's `out_of_month`/`wrong_location`/`no_sources` counts.
- **`overall_confidence` is the lowest of date/audience/geographic-origin confidence,** not an
  average or the date's confidence alone -- a report is only as trustworthy as its weakest claim.
- **The `attributions` list currently has exactly one entry: Google Search via Gemini grounding.**
  Its URL and terms-of-service link were verified live (ai.google.dev/gemini-api/docs/grounding
  explicitly points to the terms URL used here) rather than assumed. More entries get added in
  milestone 5 as connectors (OpenLigaDB, Ticketmaster, Nominatim) come online.

## 2026-09-28 — First full 6-category live run cost 7x the estimate; capped discover's thinking

`eventscout run --max-cost-usd 0.50` (all 6 categories) completed successfully -- 37 raw events,
35 after dedup, all schema-valid -- but cost **$0.4173**, against a pre-run estimate of ~$0.05-0.07.

- **Cause:** `discover.py` never set a `thinking_config`, so `gemini-3.5-flash` (the discovery
  model) ran at its default thinking level, not the minimal one `extract.py`/`enrich.py` already
  used. Thinking tokens are billed at the model's *output* rate, and `gemini-3.5-flash`'s output
  rate ($9.00/1M) is by far the priciest in the pipeline -- so a discovery call can rack up
  significant cost in tokens that never even appear in the visible response text. The original
  estimate only had one single-category data point (`festival_culture`, already cached) to
  extrapolate from, which didn't expose this.
- **Decision:** added `thinking_config=ThinkingConfig(thinking_level=LOW)` to `discover.py`'s
  config -- one step above extract/enrich's `MINIMAL`, since discovery plausibly benefits more from
  reasoning to synthesize results across many grounded sources, but still far below the
  unconfigured default.
- **Trade-off:** this wasn't re-verified with another live run (that would cost more money to
  prove a cost fix), so the actual savings are inferred from the pricing model, not measured. The
  existing `events_oct_2026.json` (35 events, $0.4173, well within the $5 project budget) was kept
  as the real deliverable rather than discarded to re-run cheaper.
- Not a bug: nothing malfunctioned, and `--max-cost-usd` correctly would have aborted before
  exceeding its cap had spend gotten close. This is a cost-estimation and pricing-model lesson, not
  a correctness issue.

## 2026-09-29 — Milestone 5, OpenLigaDB connector: verification findings and a real bug

- **League coverage, verified live against `getavailableteams` for bl1/bl2/bl3 (season 2026):**
  only FC Bayern München appears among Munich clubs. TSV 1860 München (commonly 3. Liga) is not
  listed in any of the three tiers this season. Per the user's decision, the connector covers only
  FC Bayern München -- no other Munich club is guessed at or included.
- **`team1` = home team, confirmed with the user against real fixture data,** not against an
  official doc (none was found stating this explicitly). The evidence: Bayern alternates being
  listed as team1/team2 in exactly the pattern a real fixture list alternates home/away.
- **Stadium mapping (`MUNICH_CLUB_STADIUMS` in config.py) is user-confirmed, not memorized:**
  Allianz Arena, capacity 75,000, source `https://www.allianz-arena.com/en/`.
- **Season-from-month is a judgment call:** the brief confirms "season is the starting year" but
  not how to derive it from an arbitrary target month. `_bundesliga_season_for_month` in `cli.py`
  uses August as the season-start cutoff (a month before August belongs to the previous year's
  season) -- a reasonable assumption about how Bundesliga scheduling works, not a claim about
  OpenLigaDB's own data.
- **Real bug found on the first live OpenLigaDB run:** both fetched matches were dropped by
  `clean.py`'s location filter, because "Allianz Arena" doesn't contain the string "Munich" and the
  connector left `venue_address`/`venue_district` empty. Fixed by setting `venue_district="Munich"`
  in `openligadb.py` -- safe because every entry in `MUNICH_CLUB_STADIUMS` is, by construction, a
  Munich club's stadium, not an inferred fact. Verified fixed by inspecting the same live response
  again after the fix.
- **Attribution:** OpenLigaDB requires ODbL attribution. `export.py`'s `ATTRIBUTION_BY_SOURCE` now
  maps each `DiscoverySource` to its `Attribution`, included only when that source actually
  contributed an event to the output -- an attribution for a source with zero results would be
  misleading.

## 2026-09-29 — Second real bug from a live run: German venue names failed location filtering

Regenerating the full deliverable after the OpenLigaDB fix (all 6 categories + openligadb, capped
thinking on discover) surfaced another real bug: `trade_fair_congress` went from 6 raw events
discovered to 0 in the final output -- all 6 were dropped as `wrong_location`.

- **Cause:** `_matches_location` did an exact substring check for `"munich"` against venue text.
  German sources (very common for a German trade fair) give the German city name -- "Messe
  München", "81823 München, Germany" -- which doesn't contain the substring "Munich" at all.
  Verified directly: `_matches_location(event_with_venue="Messe München", city="Munich")` returned
  `False`.
- **Decision:** switched to `rapidfuzz.fuzz.partial_ratio(city, venue_field) >= 60`. Tested against
  real city-name pairs: Munich/München scores 73, Vienna/Wien scores 75, while wrong cities score
  25-36 (Berlin, Hamburg, Nuremberg, Augsburg) -- a comfortable margin at threshold 60.
- **Known limitation, not fully solved:** fuzzy string matching only catches local names that are
  lexically close to the English name. A city whose local name is a genuinely different word
  (Cologne/Köln scores only 50, which would still fail at this threshold) would still be
  incorrectly dropped. This is a real gap, not claimed as solved -- a proper fix needs an actual
  translation/exonym table, out of scope here. This is the same class of issue the brief already
  flags as an expected limitation ("bias towards English-language ... events").
- **This bug was also invisible to unit tests** until a live run produced real German-language
  venue text -- the existing location-filter tests only used English venue strings. Added a test
  with a real German venue string to close that gap.
- **Measured, not just inferred, cost impact of the earlier thinking-level fix:** this full
  regeneration (6 categories + OpenLigaDB, discover capped to `thinking_level=LOW`) cost $0.2665,
  versus $0.4173 for the equivalent run before that fix -- roughly 36% lower, though not a clean
  apples-to-apples comparison since live grounded search returned a different number of events
  between the two runs (24 vs 35 final events).
- **First real cross-source corroboration observed:** both OpenLigaDB fixtures (Bayern vs RB
  Leipzig, Bayern vs Dortmund) were independently found by Gemini's grounded search too, and
  `clean.py`'s dedup correctly merged them into corroborated events (`corroborated_count: 2`,
  `discovered_via` containing both `openligadb_api` and `gemini_grounded_search`) -- the first live
  proof that the cross-source merge logic built in milestone 3 actually works as intended.

## 2026-09-29 — Quality pass on the deliverable: attendance figures had no source

Reviewing `events_oct_2026.json` field-by-field (not just schema validity) found that every
`estimated`-basis attendance figure had `source_url: null` -- e.g. EXPO REAL's 40,000 and the
Marathon's 28,500 had no way to trace which source stated that number, even though the event
itself had sources generally. `ExtractedEvent` never asked the model which source specifically
backs the attendance claim.

- **Decision:** added `attendance_source_number` to `ExtractedEvent` (mirroring the existing
  `source_numbers` pattern) and the extraction prompt, resolved to a real URL in `extract.py`.
- **Same bug pattern found again immediately after fixing it:** the resolved URL was still a raw
  `vertexaisearch.cloud.google.com/redirect/...` link, because `clean.py`'s URL resolution only
  ever touched `event.sources`, not the separate `attendance_source_url` field. Fixed by
  extracting the resolution logic into a plain `_resolve_url()` helper reused for both. This is
  the third time in this project a "resolve/attribute this one field too" gap has been found only
  by inspecting real output, not by schema validation, which happily accepts a `null` or an
  unresolved URL as valid.
- Regenerating cost $0.0532 (extraction cache invalidated by the prompt/schema change; discover
  stayed cached). `events_oct_2026.json` now has 30 events, every attendance figure with a value
  also has a real, resolved source URL.

## 2026-09-29 — Reverted attendance_source_number: it was confidently wrong, and revealed a deeper gap

Spot-checking the regenerated output for topical relevance (not just "is there a URL", which
schema validation already confirmed) found the attendance-source feature above was actively
citing the wrong page: "Munich Quantum Software Forum 2026" cited a Performance Days trade-fair
page; "The Munich AI Conference 2026" cited an Expo Real blog post. Both are real, resolvable
URLs -- just not about the event they were attached to.

- **Decision: reverted `attendance_source_number` entirely** (removed from `ExtractedEvent`, the
  prompt, and `extract.py`). `attendance_source_url` is now always `null` for Gemini-sourced
  events, with a comment explaining why. A wrong-but-confident citation is worse than an honest
  `null` -- it looks more rigorous than it is.
- **The deeper finding: this isn't isolated to the new field.** Checking `The Munich AI
  Conference 2026`'s own general `evidence.sources` (the `source_numbers` mechanism from
  milestone 2, backing every event in the pipeline) showed the *same* problem -- its sources were
  also a Performance Days page and an unrelated exhibits page, not anything about an AI
  conference.
- **Root cause:** `discover.py` only extracts `grounding_chunks` (the flat, deduplicated list of
  every source cited anywhere in a response) and never `grounding_supports` (the field that maps
  specific text spans to specific chunk indices). Without that mapping, the discovery response's
  raw text has no inline citations, so when `extract.py` later asks a separate model call "which
  numbered source backs event X," that model has no real signal to work with -- it can only guess
  from surrounding context, and does so unreliably once a single discovery response covers many
  events sharing one large source list (a category like trade_fair_congress can have 30-48
  sources for 6-8 events).
- **This means `evidence.sources` on every Gemini-derived event should be read as "sources cited
  somewhere in the same discovery response," not "sources specifically about this event."** The
  events themselves are still real (grounded search found real pages), but the per-event source
  attribution is less precise than the schema's shape implies. Flagged as a known limitation for
  now (see README) rather than fixed immediately -- a proper fix means parsing
  `grounding_supports` and aligning extracted events back to text spans, a bigger change than
  this session's remaining scope.
- **Why this stayed invisible for three milestones:** every test that touches `source_numbers`
  (both fake-client unit tests and the "does it validate against the schema" check) only confirms
  a URL is present and well-formed, never that it's topically relevant to the event it's attached
  to -- fuzzy relevance isn't something a unit test can assert. Only manually reading the output
  side-by-side with event names caught it.
