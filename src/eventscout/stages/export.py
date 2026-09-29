"""Export stage: assembles final, schema-validated Event objects and the
top-level output. Pure Python, no LLM calls.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime

from eventscout.cost import CostLedger
from eventscout.models import (
    Attribution,
    ConfidenceLevel,
    DiscoverySource,
    Event,
    EventAttendance,
    EventDataQuality,
    EventDates,
    EventEvidence,
    EventQuery,
    EventScale,
    EventScoutOutput,
    EventStats,
    EventTicketing,
    EventVenue,
    PipelineInfo,
    RawEvent,
    ScaleTier,
)
from eventscout.stages.clean import normalize_name
from eventscout.stages.enrich import EnrichedRawEvent

# Higher rank = more confident. Used to roll up an event's overall confidence
# to whichever of its inputs (date, audience, origin) was least confident.
_CONFIDENCE_RANK = {ConfidenceLevel.HIGH: 3, ConfidenceLevel.MEDIUM: 2, ConfidenceLevel.LOW: 1}

# Confirmed real: https://ai.google.dev/gemini-api/docs/grounding (2026-09-28),
# which points to the terms URL below for grounding-result usage requirements.
GEMINI_GROUNDING_ATTRIBUTION = Attribution(
    source="Google Search (via Gemini API grounding)",
    url="https://ai.google.dev/gemini-api/docs/grounding",
    license_or_terms="https://ai.google.dev/gemini-api/terms#grounding-with-google-search",
)

OPENLIGADB_ATTRIBUTION = Attribution(
    source="OpenLigaDB",
    url="https://www.openligadb.de/",
    license_or_terms="Open Database License (ODbL) v1.0 -- https://opendatacommons.org/licenses/odbl/1-0/",
)

# Only included when that source actually contributed an event to the output
# (see build_output) -- an attribution for a source with zero results in this
# run would be misleading.
ATTRIBUTION_BY_SOURCE: dict[DiscoverySource, Attribution] = {
    DiscoverySource.GEMINI_GROUNDED_SEARCH: GEMINI_GROUNDING_ATTRIBUTION,
    DiscoverySource.OPENLIGADB_API: OPENLIGADB_ATTRIBUTION,
}


def build_event(enriched: EnrichedRawEvent) -> Event | None:
    """Build one final Event, or None if it can't satisfy the schema.

    The only case that happens in practice: no start_date. `dates.start_date`
    is required by the final schema, but discover/extract sometimes can't
    pin one down -- such events are dropped here, not silently coerced to a
    made-up date.
    """
    raw = enriched.raw
    if raw.start_date is None:
        return None

    date_confidence = raw.date_confidence or ConfidenceLevel.HIGH
    fact_fields, inferred_fields = _classify_fields(raw)

    return Event(
        id=_make_id(raw),
        name=raw.name,
        name_local=raw.name_local,
        category=raw.category or "other",
        subcategory=raw.subcategory,
        description=raw.description[:300] if raw.description else None,
        dates=EventDates(
            start_date=raw.start_date, end_date=raw.end_date, date_confidence=date_confidence
        ),
        venue=EventVenue(
            name=raw.venue_name,
            address=raw.venue_address,
            district=raw.venue_district,
            latitude=raw.latitude,
            longitude=raw.longitude,
            is_outdoor=raw.is_outdoor,
        ),
        organizer=raw.organizer,
        url=raw.url,
        ticketing=EventTicketing(is_free=raw.is_free, price_note=raw.price_note),
        scale=EventScale(
            attendance=EventAttendance(
                value=raw.attendance_value,
                low=raw.attendance_low,
                high=raw.attendance_high,
                basis=raw.attendance_basis or "unknown",
                source_url=raw.attendance_source_url,
            ),
            exhibitors=raw.exhibitors,
            scale_tier=raw.scale_tier or _infer_scale_tier(raw.attendance_value),
        ),
        audience=enriched.audience,
        geographic_origin=enriched.geographic_origin,
        evidence=EventEvidence(
            sources=raw.sources,
            discovered_via=raw.discovered_via,
            corroborated=len(set(raw.discovered_via)) >= 2,
            fact_fields=fact_fields,
            inferred_fields=inferred_fields,
        ),
        data_quality=EventDataQuality(
            overall_confidence=_lowest_confidence(
                date_confidence, enriched.audience.confidence, enriched.geographic_origin.confidence
            )
        ),
    )


def _make_id(raw: RawEvent) -> str:
    slug = normalize_name(raw.name).replace(" ", "-")
    fingerprint = f"{raw.name}|{raw.start_date}|{raw.venue_name}"
    short_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:6]
    return f"{slug}-{raw.start_date.isoformat()}-{short_hash}"


def _infer_scale_tier(attendance_value: int | None) -> ScaleTier:
    """No thresholds are given in the brief; these are a judgment call --
    see docs/decisions.md."""
    if attendance_value is None:
        return ScaleTier.LOCAL
    if attendance_value >= 100_000:
        return ScaleTier.INTERNATIONAL
    if attendance_value >= 20_000:
        return ScaleTier.NATIONAL
    if attendance_value >= 5_000:
        return ScaleTier.REGIONAL
    return ScaleTier.LOCAL


def _classify_fields(raw: RawEvent) -> tuple[list[str], list[str]]:
    fact_fields = ["name", "dates"]
    if raw.venue_name:
        fact_fields.append("venue")
    if raw.organizer:
        fact_fields.append("organizer")
    if raw.url:
        fact_fields.append("url")
    if raw.attendance_value is not None:
        fact_fields.append("scale.attendance")
    return fact_fields, ["audience", "geographic_origin"]


def _lowest_confidence(*levels: ConfidenceLevel) -> ConfidenceLevel:
    return min(levels, key=lambda level: _CONFIDENCE_RANK[level])


def build_output(
    enriched_events: list[EnrichedRawEvent],
    *,
    city: str,
    country_code: str,
    month: str,
    models: dict[str, str],
    ledger: CostLedger,
    dropped_by_reason: dict[str, int],
) -> EventScoutOutput:
    events = []
    dropped_no_start_date = 0
    for enriched in enriched_events:
        event = build_event(enriched)
        if event is None:
            dropped_no_start_date += 1
        else:
            events.append(event)

    all_dropped = dict(dropped_by_reason)
    if dropped_no_start_date:
        all_dropped["no_start_date"] = dropped_no_start_date

    sources_used = sorted(
        {source for event in events for source in event.evidence.discovered_via},
        key=lambda s: s.value,
    )

    return EventScoutOutput(
        generated_at=datetime.now(UTC),
        query=EventQuery(city=city, country_code=country_code, month=month),
        pipeline=PipelineInfo(
            models=models,
            sources_used=sources_used,
            search_queries_executed=ledger.search_queries_executed,
            api_calls=len(ledger.calls),
            cache_hits=ledger.cache_hits,
            estimated_cost_usd=ledger.total_cost_usd,
        ),
        attributions=[ATTRIBUTION_BY_SOURCE[s] for s in sources_used if s in ATTRIBUTION_BY_SOURCE],
        stats=EventStats(
            event_count=len(events),
            by_category=dict(Counter(e.category.value for e in events)),
            by_source=dict(Counter(s.value for e in events for s in e.evidence.discovered_via)),
            corroborated_count=sum(1 for e in events if e.evidence.corroborated),
            dropped_by_reason=all_dropped,
        ),
        events=events,
    )
