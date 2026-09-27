"""Tests for the extraction stage, using a fake client (no live structured-output call)."""

import json

from conftest import FakeGeminiClient, make_response

from eventscout.cost import CostLedger
from eventscout.llm import Source
from eventscout.models import DiscoverySource, EventCategory
from eventscout.stages.extract import extract_events

SOURCES = [
    Source(url="https://example.org/a", title="Source A"),
    Source(url="https://example.org/b", title="Source B"),
]


def test_extract_events_converts_valid_json_to_raw_events():
    payload = [
        {
            "name": "Oktoberfest",
            "start_date": "2026-09-19",
            "end_date": "2026-10-04",
            "venue_name": "Theresienwiese",
            "attendance_value": 6000000,
            "attendance_basis": "reported",
            "source_numbers": [1, 2],
        }
    ]
    client = FakeGeminiClient([make_response(json.dumps(payload))])
    ledger = CostLedger(max_cost_usd=10.0)

    events = extract_events(
        client,
        text="some discovery text",
        sources=SOURCES,
        category=EventCategory.FESTIVAL_CULTURE,
        ledger=ledger,
    )

    assert len(events) == 1
    event = events[0]
    assert event.name == "Oktoberfest"
    assert event.category == EventCategory.FESTIVAL_CULTURE
    assert str(event.start_date) == "2026-09-19"
    assert event.discovered_via == [DiscoverySource.GEMINI_GROUNDED_SEARCH]
    assert [s.url for s in event.sources] == ["https://example.org/a", "https://example.org/b"]


def test_extract_events_drops_events_with_no_source_numbers():
    payload = [{"name": "Unsourced Event", "source_numbers": []}]
    client = FakeGeminiClient([make_response(json.dumps(payload))])
    ledger = CostLedger(max_cost_usd=10.0)

    events = extract_events(
        client,
        text="some discovery text",
        sources=SOURCES,
        category=EventCategory.OTHER,
        ledger=ledger,
    )

    assert events == []


def test_extract_events_returns_empty_list_for_malformed_json():
    client = FakeGeminiClient([make_response("not valid json")])
    ledger = CostLedger(max_cost_usd=10.0)

    events = extract_events(
        client,
        text="some discovery text",
        sources=SOURCES,
        category=EventCategory.OTHER,
        ledger=ledger,
    )

    assert events == []


def test_extract_events_skips_call_when_no_sources():
    client = FakeGeminiClient([])
    ledger = CostLedger(max_cost_usd=10.0)

    events = extract_events(
        client,
        text="some discovery text",
        sources=[],
        category=EventCategory.OTHER,
        ledger=ledger,
    )

    assert events == []
    assert client.call_count == 0
