"""Tests for the enrichment stage, using a fake client (no live structured-output call)."""

import json

from conftest import FakeGeminiClient, make_response

from eventscout.cost import CostLedger
from eventscout.models import RawEvent
from eventscout.stages.enrich import BATCH_SIZE, enrich_events


def make_raw_event(name="Test Event"):
    return RawEvent(name=name)


def enrichment_json(*, event_number, audience_type="b2c", confidence="medium"):
    return {
        "event_number": event_number,
        "audience_type": audience_type,
        "audience_segments": ["families"],
        "audience_industries": [],
        "audience_interests": ["culture"],
        "audience_languages": ["de", "en"],
        "audience_confidence": confidence,
        "audience_rationale": "Synthetic rationale for testing.",
        "geographic_origin_primary": [
            {"region": "Bavaria", "country_codes": ["DE"], "scope": "regional", "share": "high"}
        ],
        "geographic_origin_international_share": "low",
        "geographic_origin_confidence": confidence,
        "geographic_origin_rationale": "Synthetic rationale for testing.",
    }


def test_enrich_events_maps_results_back_by_event_number():
    events = [make_raw_event("Oktoberfest"), make_raw_event("Marathon")]
    payload = [
        enrichment_json(event_number=1, audience_type="b2c"),
        enrichment_json(event_number=2, audience_type="mixed"),
    ]
    client = FakeGeminiClient([make_response(json.dumps(payload))])
    ledger = CostLedger(max_cost_usd=10.0)

    results = enrich_events(client, events, ledger=ledger)

    assert len(results) == 2
    assert results[0].raw.name == "Oktoberfest"
    assert results[0].audience.type == "b2c"
    assert results[0].geographic_origin.primary[0].region == "Bavaria"
    assert results[1].audience.type == "mixed"


def test_enrich_events_falls_back_when_event_number_missing():
    events = [make_raw_event("Oktoberfest"), make_raw_event("Marathon")]
    payload = [enrichment_json(event_number=1)]  # event 2 missing from response
    client = FakeGeminiClient([make_response(json.dumps(payload))])
    ledger = CostLedger(max_cost_usd=10.0)

    results = enrich_events(client, events, ledger=ledger)

    assert results[0].audience.confidence == "medium"
    assert results[1].audience.confidence == "low"
    assert "failed or omitted" in results[1].audience.rationale


def test_enrich_events_falls_back_for_all_on_malformed_json():
    events = [make_raw_event("Oktoberfest")]
    client = FakeGeminiClient([make_response("not valid json")])
    ledger = CostLedger(max_cost_usd=10.0)

    results = enrich_events(client, events, ledger=ledger)

    assert results[0].audience.confidence == "low"
    assert results[0].geographic_origin.confidence == "low"


def test_enrich_events_batches_in_groups_of_batch_size():
    events = [make_raw_event(f"Event {i}") for i in range(BATCH_SIZE + 2)]
    responses = [
        make_response(json.dumps([enrichment_json(event_number=n + 1) for n in range(BATCH_SIZE)])),
        make_response(
            json.dumps([enrichment_json(event_number=1), enrichment_json(event_number=2)])
        ),
    ]
    client = FakeGeminiClient(responses)
    ledger = CostLedger(max_cost_usd=10.0)

    results = enrich_events(client, events, ledger=ledger)

    assert len(results) == BATCH_SIZE + 2
    assert client.call_count == 2  # one call per batch, not per event


def test_enrich_events_returns_empty_list_for_no_events():
    client = FakeGeminiClient([])
    ledger = CostLedger(max_cost_usd=10.0)

    results = enrich_events(client, [], ledger=ledger)

    assert results == []
    assert client.call_count == 0
