"""Gemini call wrapper: disk cache, tenacity retries, and cost recording in one place.

Every Gemini call in the pipeline goes through `generate`, never through the SDK
client directly, so caching/retries/cost tracking stay consistent everywhere.

Field names below (`usage_metadata`, `prompt_token_count`, `candidates_token_count`,
`thoughts_token_count`, `.text`, `APIError.code`) are taken from the installed
google-genai SDK's `types.py` / `errors.py` / `models.py`, not from memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from google.genai.errors import APIError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from eventscout.cache import cache_key
from eventscout.cache import get as cache_get
from eventscout.cache import put as cache_put
from eventscout.cost import CallRecord, CostLedger

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GeminiClient(Protocol):
    """The slice of the google-genai `Client.models` surface we call through.

    Kept as a Protocol (not the real SDK type) so tests can pass a fake client
    without needing network access or a real API key.
    """

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any: ...


@dataclass
class GenerateResult:
    text: str
    raw_response: Any
    cache_hit: bool


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, APIError) and exc.code in RETRYABLE_STATUS_CODES


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def _call_with_retry(client: GeminiClient, *, model: str, contents: Any, config: Any) -> Any:
    return client.generate_content(model=model, contents=contents, config=config)


def generate(
    client: GeminiClient,
    *,
    model: str,
    prompt: str,
    config: dict,
    stage: str,
    ledger: CostLedger,
    use_cache: bool = True,
) -> GenerateResult:
    """Call Gemini through the cache/retry/cost pipeline.

    `config` must be JSON-serialisable — it becomes part of the cache key.
    """
    key = cache_key(model, prompt, config)

    if use_cache:
        cached = cache_get(key)
        if cached is not None:
            ledger.record(CallRecord(stage=stage, model=model, cache_hit=True))
            return GenerateResult(text=cached["text"], raw_response=cached, cache_hit=True)

    response = _call_with_retry(client, model=model, contents=prompt, config=config)

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) or 0
    output_tokens = getattr(usage, "candidates_token_count", None) or 0
    thinking_tokens = getattr(usage, "thoughts_token_count", None) or 0

    cost = ledger.price_tokens(model, input_tokens, output_tokens, thinking_tokens)
    ledger.record(
        CallRecord(
            stage=stage,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=cost,
        )
    )

    text = getattr(response, "text", None) or ""
    if use_cache:
        cache_put(key, {"text": text})

    return GenerateResult(text=text, raw_response=response, cache_hit=False)
