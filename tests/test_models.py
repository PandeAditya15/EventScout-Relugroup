"""Validation tests for the final output schema, using a synthetic fixture event.

Synthetic = made up for schema-shape testing, not a real event. Real events must
always trace to source URLs; see docs/decisions.md for that rule.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from eventscout.models import (
    Attribution,
    Event,
    EventQuery,
    EventScoutOutput,
    EventStats,
    PipelineInfo,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "synthetic_events.json"


@pytest.fixture
def valid_event_dict() -> dict:
    data = json.loads(FIXTURE_PATH.read_text())
    return data["valid_event"]


def test_valid_synthetic_event_parses(valid_event_dict):
    event = Event.model_validate(valid_event_dict)
    assert event.name == "Oktoberfest"
    assert event.category == "festival_culture"
    assert event.scale.attendance.basis == "reported"
    assert event.audience.confidence == "high"


def test_event_missing_required_field_rejected(valid_event_dict):
    del valid_event_dict["dates"]
    with pytest.raises(ValidationError):
        Event.model_validate(valid_event_dict)


def test_event_rejects_bad_category_enum(valid_event_dict):
    valid_event_dict["category"] = "not_a_real_category"
    with pytest.raises(ValidationError):
        Event.model_validate(valid_event_dict)


def test_description_over_300_chars_rejected(valid_event_dict):
    valid_event_dict["description"] = "x" * 301
    with pytest.raises(ValidationError):
        Event.model_validate(valid_event_dict)


def test_full_output_wraps_validated_event(valid_event_dict):
    event = Event.model_validate(valid_event_dict)
    output = EventScoutOutput(
        generated_at=datetime.now(),
        query=EventQuery(city="Munich", country_code="DE", month="2026-10"),
        pipeline=PipelineInfo(
            models={"discovery": "TODO(verify)", "cheap": "TODO(verify)"},
            sources_used=["gemini_grounded_search"],
            search_queries_executed=1,
            api_calls=1,
            cache_hits=0,
            estimated_cost_usd=0.0,
        ),
        attributions=[
            Attribution(source="Example", url="https://example.org", license_or_terms="none")
        ],
        stats=EventStats(
            event_count=1,
            by_category={"festival_culture": 1},
            by_source={"gemini_grounded_search": 1},
            corroborated_count=0,
            dropped_by_reason={},
        ),
        events=[event],
    )
    assert output.stats.event_count == len(output.events) == 1
