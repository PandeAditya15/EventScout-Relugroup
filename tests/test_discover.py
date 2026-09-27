"""Tests for the discovery stage, using a fake client (no live grounded search)."""

from conftest import FakeGeminiClient, make_grounded_response

from eventscout.cost import CostLedger
from eventscout.models import EventCategory
from eventscout.stages.discover import discover_category


def test_discover_category_returns_text_sources_and_query_count():
    urls = ["https://example.org/messe", "https://example.org/oktoberfest"]
    client = FakeGeminiClient([make_grounded_response("Found two events...", urls)])
    ledger = CostLedger(max_cost_usd=10.0)

    result = discover_category(
        client,
        category=EventCategory.FESTIVAL_CULTURE,
        city="Munich",
        country_code="DE",
        month="2026-10",
        ledger=ledger,
    )

    assert result.category == EventCategory.FESTIVAL_CULTURE
    assert result.text == "Found two events..."
    assert [s.url for s in result.sources] == urls
    assert result.search_queries_executed == 2
    assert client.call_count == 1


def test_discover_category_prompt_includes_city_country_and_month():
    client = FakeGeminiClient([make_grounded_response("no events found", [])])
    ledger = CostLedger(max_cost_usd=10.0)
    captured = {}

    original_generate_content = client.generate_content

    def spy(*, model, contents, config):
        captured["prompt"] = contents
        return original_generate_content(model=model, contents=contents, config=config)

    client.generate_content = spy

    discover_category(
        client,
        category=EventCategory.SPORTS,
        city="Munich",
        country_code="DE",
        month="2026-10",
        ledger=ledger,
    )

    assert "Munich" in captured["prompt"]
    assert "DE" in captured["prompt"]
    assert "2026-10" in captured["prompt"]
