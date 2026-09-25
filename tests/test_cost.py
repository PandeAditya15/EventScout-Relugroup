"""Pure-logic tests for the cost ledger, using synthetic prices (not real Gemini rates)."""

import pytest

import eventscout.cost as cost_module
from eventscout.cost import BudgetExceededError, CallRecord, CostLedger


@pytest.fixture(autouse=True)
def synthetic_pricing(monkeypatch):
    monkeypatch.setitem(
        cost_module.PRICING,
        "tokens_per_1m_usd",
        {"test-model": {"input": 1.0, "output": 2.0, "thinking": 4.0}},
    )
    monkeypatch.setitem(cost_module.PRICING, "grounded_search_per_1k_queries_usd", 10.0)


def test_price_tokens_uses_configured_rates():
    ledger = CostLedger(max_cost_usd=10.0)
    cost = ledger.price_tokens(
        "test-model", input_tokens=1_000_000, output_tokens=500_000, thinking_tokens=250_000
    )
    assert cost == pytest.approx(1.0 + 1.0 + 1.0)


def test_price_tokens_unpriced_model_returns_zero():
    ledger = CostLedger(max_cost_usd=10.0)
    assert ledger.price_tokens("unknown-model", 1000, 1000, 0) == 0.0


def test_price_search_queries():
    ledger = CostLedger(max_cost_usd=10.0)
    assert ledger.price_search_queries(500) == pytest.approx(5.0)


def test_check_budget_raises_when_exceeded():
    ledger = CostLedger(max_cost_usd=1.0)
    with pytest.raises(BudgetExceededError):
        ledger.check_budget(1.5)


def test_check_budget_allows_under_cap():
    ledger = CostLedger(max_cost_usd=1.0)
    ledger.check_budget(0.5)


def test_summary_tracks_calls_and_cache_hits():
    ledger = CostLedger(max_cost_usd=10.0)
    ledger.record(CallRecord(stage="discover", model="test-model", cost_usd=1.0))
    ledger.record(CallRecord(stage="extract", model="test-model", cost_usd=0.0, cache_hit=True))
    assert ledger.total_cost_usd == pytest.approx(1.0)
    assert ledger.cache_hits == 1
    assert "$1.0000" in ledger.summary()
