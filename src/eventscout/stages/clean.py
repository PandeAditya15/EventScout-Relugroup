"""Clean stage: pure Python, no LLM. Resolves redirect URLs, filters events to
the target month/city, normalises names, and merges duplicates found by more
than one source.

Runs in this order because each step narrows the input for the next: resolving
URLs first means later steps see real publisher domains; filtering before
dedup means we're not fuzzy-matching events we're about to throw away anyway.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date

import httpx
from rapidfuzz import fuzz

from eventscout.cache import get as cache_get
from eventscout.cache import put as cache_put
from eventscout.models import RawEvent, SourceRef

NAME_SIMILARITY_THRESHOLD = 85  # rapidfuzz score (0-100) above which two names count as "the same"


@dataclass
class CleanResult:
    events: list[RawEvent]
    dropped_by_reason: dict[str, int] = field(default_factory=dict)


# --- Step 1: resolve grounding redirect URLs --------------------------------


def resolve_source_urls(sources: list[SourceRef], client: httpx.Client) -> list[SourceRef]:
    """Follow each source's URL to its final destination (cached).

    Grounding responses cite `vertexaisearch.cloud.google.com/.../redirect`
    URLs, not the real article -- these need resolving before they're useful
    as evidence links. If resolution fails, the original URL is kept as-is
    rather than dropping the source.
    """
    return [_resolve_one(source, client) for source in sources]


def _resolve_one(source: SourceRef, client: httpx.Client) -> SourceRef:
    resolved_url, publisher_domain = _resolve_url(source.url, client)
    return source.model_copy(update={"url": resolved_url, "publisher_domain": publisher_domain})


def _resolve_url(url: str, client: httpx.Client) -> tuple[str, str | None]:
    """Resolve one URL to its final destination (cached). Used for both
    per-source URLs and the standalone `attendance_source_url` -- any
    redirect link cited anywhere in a RawEvent needs the same treatment, or a
    reader following the "cited" attendance figure would land on Google's
    redirect service instead of the real page."""
    key = "resolve_url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = cache_get(key)
    if cached is not None:
        return cached["resolved_url"], cached["publisher_domain"]

    try:
        response = client.get(url, follow_redirects=True, timeout=5.0)
        resolved_url = str(response.url)
    except httpx.HTTPError:
        resolved_url = url  # flagged by being identical to the original

    publisher_domain = httpx.URL(resolved_url).host
    cache_put(key, {"resolved_url": resolved_url, "publisher_domain": publisher_domain})
    return resolved_url, publisher_domain


# --- Step 2: month-overlap and location filter ------------------------------


def filter_by_month_and_location(
    events: list[RawEvent], *, month: str, city: str
) -> tuple[list[RawEvent], int, int]:
    """Keep events whose [start, end] overlaps `month` (YYYY-MM) and whose
    venue looks like it's in `city`. Missing dates or missing venue info are
    not treated as a mismatch -- there's no positive evidence to drop on."""
    month_start, month_end = _month_bounds(month)

    kept = []
    dropped_out_of_month = 0
    dropped_wrong_location = 0
    for event in events:
        if not _overlaps_month(event, month_start, month_end):
            dropped_out_of_month += 1
            continue
        if not _matches_location(event, city):
            dropped_wrong_location += 1
            continue
        kept.append(event)

    return kept, dropped_out_of_month, dropped_wrong_location


def _month_bounds(month: str) -> tuple[date, date]:
    year, month_num = (int(part) for part in month.split("-"))
    last_day = monthrange(year, month_num)[1]
    return date(year, month_num, 1), date(year, month_num, last_day)


def _overlaps_month(event: RawEvent, month_start: date, month_end: date) -> bool:
    if event.start_date is None:
        return True  # unknown date: no evidence to drop on
    end = event.end_date or event.start_date
    return event.start_date <= month_end and end >= month_start


CITY_MATCH_THRESHOLD = 60  # rapidfuzz partial_ratio score


def _matches_location(event: RawEvent, city: str) -> bool:
    """Fuzzy, not exact substring -- German-sourced venues routinely give the
    city's German name (e.g. "München" for Munich), which found live: an
    exact-substring check against the English city name dropped every event
    at a German-language venue as wrong_location. Fuzzy matching handles
    close variants (München/Munich, Wien/Vienna) but isn't a real
    translation table -- a city whose local name is lexically unrelated to
    its English name (Cologne/Köln) can still slip through as a false
    negative. See docs/decisions.md."""
    fields = [event.venue_name, event.venue_address, event.venue_district]
    if not any(fields):
        return True  # unknown location: no evidence to drop on
    city_lower = city.lower()
    return any(
        f and fuzz.partial_ratio(city_lower, f.lower()) >= CITY_MATCH_THRESHOLD for f in fields
    )


# --- Step 3: name normalisation ----------------------------------------------

_ORDINAL_RE = re.compile(r"\b\d+(st|nd|rd|th)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, strip years/ordinals/punctuation, and fold diacritics
    (Muenchen/München) so name matching isn't defeated by accents or edition
    numbers. Genuinely different-language names (e.g. a German vs English
    title for the same event) are left for rapidfuzz's similarity scoring in
    dedupe_events, not exact normalisation."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    folded = folded.lower()
    folded = _YEAR_RE.sub("", folded)
    folded = _ORDINAL_RE.sub("", folded)
    folded = _PUNCTUATION_RE.sub(" ", folded)
    return _WHITESPACE_RE.sub(" ", folded).strip()


# --- Step 4: cross-source fuzzy dedupe --------------------------------------


def dedupe_events(events: list[RawEvent]) -> list[RawEvent]:
    """Merge events that are the same real-world event: similar normalised
    names, and overlapping (or unknown) dates."""
    merged: list[RawEvent] = []
    for event in events:
        match_index = _find_match(merged, event)
        if match_index is None:
            merged.append(event)
        else:
            merged[match_index] = _merge_events(merged[match_index], event)
    return merged


def _find_match(existing: list[RawEvent], candidate: RawEvent) -> int | None:
    candidate_name = normalize_name(candidate.name)
    for i, other in enumerate(existing):
        similarity = fuzz.token_sort_ratio(candidate_name, normalize_name(other.name))
        if similarity >= NAME_SIMILARITY_THRESHOLD and _dates_overlap(candidate, other):
            return i
    return None


def _dates_overlap(a: RawEvent, b: RawEvent) -> bool:
    if a.start_date is None or b.start_date is None:
        return True  # can't compare; don't block a likely match on missing data
    a_end = a.end_date or a.start_date
    b_end = b.end_date or b.start_date
    return a.start_date <= b_end and b.start_date <= a_end


def _merge_events(a: RawEvent, b: RawEvent) -> RawEvent:
    """Field-by-field: keep whichever side has a value, preferring `a`."""
    merged_fields = {
        name: getattr(a, name) if getattr(a, name) is not None else getattr(b, name)
        for name in type(a).model_fields
        if name not in {"sources", "discovered_via"}
    }
    merged_fields["sources"] = _union_sources(a.sources, b.sources)
    merged_fields["discovered_via"] = list(dict.fromkeys(a.discovered_via + b.discovered_via))
    return RawEvent(**merged_fields)


def _union_sources(a: list[SourceRef], b: list[SourceRef]) -> list[SourceRef]:
    seen: dict[str, SourceRef] = {s.url: s for s in a}
    for s in b:
        seen.setdefault(s.url, s)
    return list(seen.values())


# --- Step 5: drop unsourced events -------------------------------------------


def drop_unsourced(events: list[RawEvent]) -> tuple[list[RawEvent], int]:
    kept = [e for e in events if e.sources]
    return kept, len(events) - len(kept)


# --- Orchestrator ------------------------------------------------------------


def clean_events(
    events: list[RawEvent], *, month: str, city: str, http_client: httpx.Client
) -> CleanResult:
    for event in events:
        event.sources = resolve_source_urls(event.sources, http_client)
        if event.attendance_source_url is not None:
            event.attendance_source_url, _ = _resolve_url(event.attendance_source_url, http_client)

    filtered, dropped_out_of_month, dropped_wrong_location = filter_by_month_and_location(
        events, month=month, city=city
    )
    deduped = dedupe_events(filtered)
    sourced, dropped_unsourced_count = drop_unsourced(deduped)

    return CleanResult(
        events=sourced,
        dropped_by_reason={
            "out_of_month": dropped_out_of_month,
            "wrong_location": dropped_wrong_location,
            "no_sources": dropped_unsourced_count,
        },
    )
