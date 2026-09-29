"""Tests for the clean stage. All synthetic data -- these test pure logic
(date overlap, name normalisation, dedup), not real event facts. URL
resolution uses httpx.MockTransport, so no real network call is ever made.
"""

from datetime import date

import httpx

from eventscout.models import DiscoverySource, RawEvent, SourceRef
from eventscout.stages.clean import (
    CleanResult,
    clean_events,
    dedupe_events,
    drop_unsourced,
    filter_by_month_and_location,
    normalize_name,
    resolve_source_urls,
)


def make_event(
    name="Test Event",
    start_date=None,
    end_date=None,
    venue_name=None,
    venue_address=None,
    sources=None,
):
    # `sources=None` means "use the default source"; `sources=[]` must stay
    # empty, so this can't be a plain `sources or [...]` (empty list is falsy).
    if sources is None:
        sources = [SourceRef(url="https://example.org/a")]
    return RawEvent(
        name=name,
        start_date=start_date,
        end_date=end_date,
        venue_name=venue_name,
        venue_address=venue_address,
        sources=sources,
        discovered_via=[DiscoverySource.GEMINI_GROUNDED_SEARCH],
    )


# --- resolve_source_urls -----------------------------------------------------


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolve_source_urls_follows_redirect(isolated_cache):
    def handler(request):
        if str(request.url) == "https://vertexaisearch.example/redirect/abc":
            return httpx.Response(302, headers={"Location": "https://real-site.example/article"})
        return httpx.Response(200)

    client = mock_client(handler)
    source = SourceRef(url="https://vertexaisearch.example/redirect/abc")

    resolved = resolve_source_urls([source], client)

    assert resolved[0].url == "https://real-site.example/article"
    assert resolved[0].publisher_domain == "real-site.example"


def test_resolve_source_urls_keeps_original_url_on_failure(isolated_cache):
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    client = mock_client(handler)
    source = SourceRef(url="https://example.org/unreachable")

    resolved = resolve_source_urls([source], client)

    assert resolved[0].url == "https://example.org/unreachable"


def test_resolve_source_urls_caches_result(isolated_cache):
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        return httpx.Response(200, request=request)

    client = mock_client(handler)
    source = SourceRef(url="https://example.org/a")

    resolve_source_urls([source], client)
    resolve_source_urls([source], client)

    assert call_count["n"] == 1


# --- filter_by_month_and_location -------------------------------------------


def test_filter_drops_event_entirely_before_target_month():
    event = make_event(start_date=date(2026, 8, 1), end_date=date(2026, 8, 5))

    kept, out_of_month, wrong_location = filter_by_month_and_location(
        [event], month="2026-10", city="Munich"
    )

    assert kept == []
    assert out_of_month == 1
    assert wrong_location == 0


def test_filter_keeps_event_overlapping_month_boundary():
    event = make_event(start_date=date(2026, 9, 25), end_date=date(2026, 10, 2))

    kept, out_of_month, wrong_location = filter_by_month_and_location(
        [event], month="2026-10", city="Munich"
    )

    assert kept == [event]


def test_filter_keeps_event_with_unknown_dates():
    event = make_event(start_date=None)

    kept, out_of_month, _ = filter_by_month_and_location([event], month="2026-10", city="Munich")

    assert kept == [event]
    assert out_of_month == 0


def test_filter_drops_event_in_wrong_city():
    event = make_event(
        start_date=date(2026, 10, 5), venue_name="Arena", venue_address="Berlin, Germany"
    )

    kept, _, wrong_location = filter_by_month_and_location([event], month="2026-10", city="Munich")

    assert kept == []
    assert wrong_location == 1


def test_filter_keeps_event_with_german_language_venue():
    # Found live: German-sourced venues give the German city name ("München"),
    # which an exact-substring check against "Munich" doesn't match.
    event = make_event(
        start_date=date(2026, 10, 5),
        venue_name="Messe München",
        venue_address="81823 München, Germany",
    )

    kept, _, wrong_location = filter_by_month_and_location([event], month="2026-10", city="Munich")

    assert kept == [event]
    assert wrong_location == 0


def test_filter_keeps_event_with_unknown_location():
    event = make_event(start_date=date(2026, 10, 5), venue_name=None)

    kept, _, wrong_location = filter_by_month_and_location([event], month="2026-10", city="Munich")

    assert kept == [event]
    assert wrong_location == 0


# --- normalize_name -----------------------------------------------------------


def test_normalize_name_strips_year_ordinal_punctuation_and_diacritics():
    assert normalize_name("Oktoberfest 2026 (191st Edition)!") == "oktoberfest edition"
    assert normalize_name("München Marathon") == "munchen marathon"


# --- dedupe_events -------------------------------------------------------------


def test_dedupe_merges_similar_names_with_overlapping_dates():
    a = make_event(
        name="Munich Marathon 2026",
        start_date=date(2026, 10, 11),
        sources=[SourceRef(url="https://a.example/1")],
    )
    b = make_event(
        name="Munich Marathon (2026)",
        start_date=date(2026, 10, 11),
        sources=[SourceRef(url="https://b.example/2")],
    )

    merged = dedupe_events([a, b])

    assert len(merged) == 1
    assert {s.url for s in merged[0].sources} == {"https://a.example/1", "https://b.example/2"}


def test_dedupe_keeps_distinct_events_separate():
    a = make_event(name="Oktoberfest", start_date=date(2026, 10, 1))
    b = make_event(name="Munich Marathon", start_date=date(2026, 10, 11))

    merged = dedupe_events([a, b])

    assert len(merged) == 2


def test_dedupe_does_not_merge_same_name_on_different_dates():
    a = make_event(name="Auer Dult", start_date=date(2026, 4, 1))
    b = make_event(name="Auer Dult", start_date=date(2026, 10, 17))

    merged = dedupe_events([a, b])

    assert len(merged) == 2


# --- drop_unsourced -------------------------------------------------------------


def test_drop_unsourced_removes_events_with_no_sources():
    sourced = make_event(name="Has Sources")
    unsourced = make_event(name="No Sources", sources=[])

    kept, dropped_count = drop_unsourced([sourced, unsourced])

    assert kept == [sourced]
    assert dropped_count == 1


# --- clean_events orchestrator --------------------------------------------------


def test_clean_events_resolves_attendance_source_url_too(isolated_cache):
    # Found live: attendance_source_url was left as a raw Google redirect
    # link because only `event.sources` went through resolve_source_urls.
    def handler(request):
        if str(request.url) == "https://vertexaisearch.example/redirect/attendance":
            return httpx.Response(302, headers={"Location": "https://real-site.example/numbers"})
        return httpx.Response(200)

    client = mock_client(handler)
    event = make_event(name="Big Fair", start_date=date(2026, 10, 5))
    event.attendance_source_url = "https://vertexaisearch.example/redirect/attendance"

    result = clean_events([event], month="2026-10", city="Munich", http_client=client)

    assert result.events[0].attendance_source_url == "https://real-site.example/numbers"


def test_clean_events_end_to_end(isolated_cache):
    client = mock_client(lambda request: httpx.Response(200))
    events = [
        make_event(name="Oktoberfest 2026", start_date=date(2026, 10, 1)),
        make_event(name="Some Berlin Thing", start_date=date(2026, 10, 5), venue_address="Berlin"),
        make_event(name="No Source Event", start_date=date(2026, 10, 5), sources=[]),
    ]

    result = clean_events(events, month="2026-10", city="Munich", http_client=client)

    assert isinstance(result, CleanResult)
    assert [e.name for e in result.events] == ["Oktoberfest 2026"]
    assert result.dropped_by_reason == {
        "out_of_month": 0,
        "wrong_location": 1,
        "no_sources": 1,
    }
