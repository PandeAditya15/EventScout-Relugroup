"""Tests for the OpenLigaDB connector, using a real (trimmed) response fixture
served over httpx.MockTransport -- no live network call.
"""

import json
from datetime import date
from pathlib import Path

import httpx

from eventscout.connectors.openligadb import fetch_munich_home_matches

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "openligadb_bl1_2026_real.json"


def mock_client() -> httpx.Client:
    fixture = json.loads(FIXTURE_PATH.read_text())

    def handler(request):
        return httpx.Response(200, json=fixture)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_munich_home_matches_keeps_only_bayern_home_in_target_month(isolated_cache):
    events = fetch_munich_home_matches(season=2026, month="2026-10", http_client=mock_client())

    assert len(events) == 1
    event = events[0]
    assert event.name == "FC Bayern München vs RB Leipzig"
    assert event.start_date == date(2026, 10, 17)
    assert event.venue_name == "Allianz Arena"
    assert event.venue_district == "Munich"  # so clean.py's location filter doesn't drop it


def test_fetch_munich_home_matches_excludes_away_matches():
    # Fixture includes a Bayern *away* match (FC Schalke 04 vs Bayern) in
    # September -- confirms only home matches (team1 = Bayern) are kept.
    events = fetch_munich_home_matches(season=2026, month="2026-09", http_client=mock_client())

    assert events == []


def test_fetch_munich_home_matches_sets_estimated_attendance_from_capacity():
    events = fetch_munich_home_matches(season=2026, month="2026-10", http_client=mock_client())

    event = events[0]
    assert event.attendance_high == 75_000
    assert event.attendance_basis == "estimated"
    assert event.attendance_source_url == "https://www.allianz-arena.com/en/"
    assert event.discovered_via == ["openligadb_api"]


def test_fetch_munich_home_matches_returns_empty_list_on_request_failure():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    events = fetch_munich_home_matches(season=2026, month="2026-10", http_client=client)

    assert events == []
