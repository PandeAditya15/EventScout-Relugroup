"""Tests for the Gemini wrapper (cache, retries, cost), using a fake client.

No network access and no real API key needed — FakeGeminiClient stands in for
google.genai's Client.models.
"""

from types import SimpleNamespace

import pytest
from google.genai.errors import APIError

import eventscout.cache as cache_module
from eventscout.cost import CostLedger
from eventscout.llm import GenerateResult, generate


def make_response(text: str, input_tokens=10, output_tokens=5, thinking_tokens=0):
    usage = SimpleNamespace(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
        thoughts_token_count=thinking_tokens,
    )
    return SimpleNamespace(text=text, usage_metadata=usage)


class FakeGeminiClient:
    """Returns queued responses/exceptions in order, one per call."""

    def __init__(self, results):
        self._results = list(results)
        self.call_count = 0

    def generate_content(self, *, model, contents, config):
        self.call_count += 1
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path)


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
