"""Tests for the export stage. All synthetic data -- pure assembly logic, no LLM calls."""

from datetime import date

from eventscout.cost import CallRecord, CostLedger
from eventscout.models import (
    DiscoverySource,
    EventAudience,
    EventCategory,
    EventGeographicOrigin,
    RawEvent,
    SourceRef,
)
from eventscout.stages.enrich import EnrichedRawEvent
from eventscout.stages.export import build_event, build_output


def make_enriched(
    name="Test Event",
    start_date=date(2026, 10, 5),
    attendance_value=None,
    sources=None,
    discovered_via=None,
    category=EventCategory.FESTIVAL_CULTURE,
):
    raw = RawEvent(
        name=name,
        category=category,
        start_date=start_date,
        venue_name="Some Venue",
        attendance_value=attendance_value,
        sources=sources if sources is not None else [SourceRef(url="https://example.org/a")],
        discovered_via=discovered_via or [DiscoverySource.GEMINI_GROUNDED_SEARCH],
    )
    audience = EventAudience(type="b2c", confidence="medium", rationale="Synthetic rationale.")
    geo = EventGeographicOrigin(confidence="medium", rationale="Synthetic rationale.")
    return EnrichedRawEvent(raw=raw, audience=audience, geographic_origin=geo)


def test_build_event_returns_none_when_start_date_missing():
    enriched = make_enriched(start_date=None)

    assert build_event(enriched) is None


def test_build_event_assembles_valid_event():
    enriched = make_enriched(name="Oktoberfest 2026", attendance_value=6_000_000)

    event = build_event(enriched)

    assert event is not None
    assert event.name == "Oktoberfest 2026"
    assert event.id.startswith("oktoberfest-2026-10-05-")
    assert event.scale.scale_tier == "international"
    assert event.evidence.corroborated is False
    assert "audience" in event.evidence.inferred_fields
    assert "name" in event.evidence.fact_fields


def test_build_event_marks_corroborated_with_two_discovery_sources():
    enriched = make_enriched(
        discovered_via=[DiscoverySource.GEMINI_GROUNDED_SEARCH, DiscoverySource.TICKETMASTER_API]
    )

    event = build_event(enriched)

    assert event.evidence.corroborated is True


def test_build_event_scale_tier_thresholds():
    assert build_event(make_enriched(attendance_value=None)).scale.scale_tier == "local"
    assert build_event(make_enriched(attendance_value=1_000)).scale.scale_tier == "local"
    assert build_event(make_enriched(attendance_value=5_000)).scale.scale_tier == "regional"
    assert build_event(make_enriched(attendance_value=20_000)).scale.scale_tier == "national"
    assert build_event(make_enriched(attendance_value=100_000)).scale.scale_tier == "international"


def test_build_event_overall_confidence_takes_the_lowest():
    enriched = make_enriched()
    enriched.audience.confidence = "low"

    event = build_event(enriched)

    assert event.data_quality.overall_confidence == "low"


def test_build_output_aggregates_stats_and_drops_events_with_no_start_date():
    with_date = make_enriched(name="Has Date", start_date=date(2026, 10, 5))
    without_date = make_enriched(name="No Date", start_date=None)
    ledger = CostLedger(max_cost_usd=10.0)
    ledger.record(CallRecord(stage="discover", model="m", search_queries=3, cost_usd=0.01))

    output = build_output(
        [with_date, without_date],
        city="Munich",
        country_code="DE",
        month="2026-10",
        models={"discovery": "m", "cheap": "m"},
        ledger=ledger,
        dropped_by_reason={"out_of_month": 2},
    )

    assert output.stats.event_count == 1
    assert output.stats.dropped_by_reason == {"out_of_month": 2, "no_start_date": 1}
    assert output.stats.by_category == {"festival_culture": 1}
    assert output.pipeline.search_queries_executed == 3
    assert output.pipeline.estimated_cost_usd == 0.01
    assert len(output.attributions) == 1
