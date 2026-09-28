"""Tests for the extraction stage, using a fake client (no live structured-output call)."""

import json
from pathlib import Path

from conftest import FakeGeminiClient, make_response

from eventscout.cost import CostLedger
from eventscout.llm import Source
from eventscout.models import DiscoverySource, EventCategory
from eventscout.stages.extract import extract_events

SOURCES = [
    Source(url="https://example.org/a", title="Source A"),
    Source(url="https://example.org/b", title="Source B"),
]

REAL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gemini_extract_response_real.json"


def test_extract_events_parses_a_real_trimmed_gemini_response():
    """Uses text trimmed from an actual gemini-3.5-flash-lite structured-output
    call (see the fixture file), not synthetic JSON we wrote by hand -- this
    catches real quirks (unicode, exact field shape) a hand-crafted payload
    could accidentally paper over."""
    real_events = json.loads(REAL_FIXTURE_PATH.read_text())["events"]
    # The real run cited sources 1-4; only the first two are needed here.
    real_sources = [
        Source(url="https://www.oktoberfest.de/en", title="oktoberfest.de"),
        Source(url="https://en.wikipedia.org/wiki/Oktoberfest", title="wikipedia.org"),
        Source(
            url="https://www.muenchen.de/en/shopping/auer-dult-munich-dates-tips",
            title="muenchen.de",
        ),
        Source(url="https://example.org/auer-dult-extra", title="another source"),
    ]
    client = FakeGeminiClient([make_response(json.dumps(real_events))])
    ledger = CostLedger(max_cost_usd=10.0)

    events = extract_events(
        client,
        text="real discovery text",
        sources=real_sources,
        category=EventCategory.FESTIVAL_CULTURE,
        ledger=ledger,
    )

    assert [e.name for e in events] == ["Oktoberfest 2026", "Auer Dult – Kirchweihdult 2026"]
    oktoberfest = events[0]
    assert oktoberfest.attendance_value == 6000000
    assert oktoberfest.attendance_basis == "reported"
    assert str(oktoberfest.start_date) == "2026-09-19"
    assert oktoberfest.venue_district == "Ludwigsvorstadt-Isarvorstadt"
    assert [s.url for s in oktoberfest.sources] == [
        "https://www.oktoberfest.de/en",
        "https://en.wikipedia.org/wiki/Oktoberfest",
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
