"""Tests for the Gemini wrapper: cache, retries, cost recording, grounding parsing."""

import pytest
from conftest import FakeGeminiClient, make_grounded_response, make_response
from google.genai.errors import APIError

from eventscout.cost import BudgetExceededError, CallRecord, CostLedger
from eventscout.llm import GenerateResult, generate


def test_generate_calls_client_and_records_cost():
    client = FakeGeminiClient([make_response("hello")])
    ledger = CostLedger(max_cost_usd=10.0)

    result = generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert isinstance(result, GenerateResult)
    assert result.text == "hello"
    assert result.cache_hit is False
    assert client.call_count == 1
    assert len(ledger.calls) == 1
    assert ledger.calls[0].input_tokens == 10


def test_generate_uses_cache_on_second_call():
    client = FakeGeminiClient([make_response("hello")])
    ledger = CostLedger(max_cost_usd=10.0)

    generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)
    result = generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert result.cache_hit is True
    assert client.call_count == 1  # second call served from cache, client not hit again
    assert ledger.cache_hits == 1


def test_generate_retries_on_retryable_error_then_succeeds():
    client = FakeGeminiClient([APIError(429, {}), make_response("ok after retry")])
    ledger = CostLedger(max_cost_usd=10.0)

    result = generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert result.text == "ok after retry"
    assert client.call_count == 2


def test_generate_does_not_retry_non_retryable_error():
    client = FakeGeminiClient([APIError(400, {})])
    ledger = CostLedger(max_cost_usd=10.0)

    with pytest.raises(APIError):
        generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert client.call_count == 1


def test_grounding_sources_and_search_queries_survive_a_cache_hit():
    urls = ["https://example.org/a", "https://example.org/b"]
    client = FakeGeminiClient([make_grounded_response("found some events", urls)])
    ledger = CostLedger(max_cost_usd=10.0)

    first = generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)
    second = generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert first.cache_hit is False
    assert [s.url for s in first.sources] == urls
    assert first.search_queries_executed == 2

    assert second.cache_hit is True
    assert [s.url for s in second.sources] == urls
    assert second.search_queries_executed == 2

    # The ledger's own tally must count the cached call's searches too --
    # not just the GenerateResult -- otherwise a run's reported search-query
    # total silently drops to 0 for every category served from cache.
    assert ledger.search_queries_executed == 4
    assert client.call_count == 1


def test_generate_refuses_a_live_call_once_budget_is_already_spent():
    client = FakeGeminiClient([make_response("should never be reached")])
    ledger = CostLedger(max_cost_usd=1.0)
    ledger.record(CallRecord(stage="discover", model="m", cost_usd=1.5))  # already over budget

    with pytest.raises(BudgetExceededError):
        generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert client.call_count == 0


def test_generate_allows_a_cache_hit_even_when_budget_is_spent():
    client = FakeGeminiClient([make_response("hello")])
    ledger = CostLedger(max_cost_usd=10.0)
    generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    ledger.record(CallRecord(stage="discover", model="m", cost_usd=10.0))  # now over budget

    result = generate(client, model="m", prompt="p", config={}, stage="discover", ledger=ledger)

    assert result.cache_hit is True
    assert client.call_count == 1  # never re-hit the client; cache reads bypass the budget check
