"""Gemini call wrapper: disk cache, tenacity retries, and cost recording in one place.

Every Gemini call in the pipeline goes through `generate`, never through the SDK
client directly. This is also where grounding metadata (cited sources, executed
search-query count) gets parsed off the raw response -- and cached alongside the
text, so a cache hit returns the same GenerateResult shape as a fresh call
instead of silently dropping the sources a grounded call found.

Field names below (`usage_metadata`, `prompt_token_count`, `candidates_token_count`,
`thoughts_token_count`, `.text`, `.candidates`, `.grounding_metadata`,
`.grounding_chunks`, `.web.uri`/`.web.title`, `.web_search_queries`,
`APIError.code`) are taken from the installed google-genai SDK's `types.py` /
`errors.py` / `models.py`, not from memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
class Source:
    url: str
    title: str | None = None


@dataclass
class GenerateResult:
    text: str
    cache_hit: bool
    sources: list[Source] = field(default_factory=list)
    search_queries_executed: int = 0


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


def _extract_grounding(response: Any) -> tuple[list[Source], int]:
    """Pull cited sources and the executed search-query count off a response.

    Only grounded calls (tools=[google_search]) populate grounding_metadata;
    a plain structured-output call simply has none, so this returns ([], 0).
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return [], 0

    metadata = getattr(candidates[0], "grounding_metadata", None)
    if metadata is None:
        return [], 0

    chunks = getattr(metadata, "grounding_chunks", None) or []
    sources = [
        Source(url=chunk.web.uri, title=chunk.web.title)
        for chunk in chunks
        if getattr(chunk, "web", None) is not None and chunk.web.uri
    ]
    search_queries = len(getattr(metadata, "web_search_queries", None) or [])
    return sources, search_queries


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

    `config` is passed straight through to the SDK as the request config (it
    may contain SDK objects like `types.Tool`, not just plain JSON values) --
    `cache_key` handles hashing it safely.
    """
    key = cache_key(model, prompt, config)

    if use_cache:
        cached = cache_get(key)
        if cached is not None:
            cached_search_queries = cached.get("search_queries_executed", 0)
            ledger.record(
                CallRecord(
                    stage=stage,
                    model=model,
                    cache_hit=True,
                    search_queries=cached_search_queries,
                )
            )
            sources = [Source(**s) for s in cached.get("sources", [])]
            return GenerateResult(
                text=cached["text"],
                cache_hit=True,
                sources=sources,
                search_queries_executed=cached_search_queries,
            )

    # We can't know this call's exact cost until it returns (token counts
    # aren't known upfront), so the budget cap is enforced by refusing to
    # start a new priced call once the run has already reached it -- not by
    # pre-computing an estimate for this specific call.
    ledger.check_budget(0.0)

    response = _call_with_retry(client, model=model, contents=prompt, config=config)

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) or 0
    output_tokens = getattr(usage, "candidates_token_count", None) or 0
    thinking_tokens = getattr(usage, "thoughts_token_count", None) or 0
    sources, search_queries = _extract_grounding(response)

    cost = ledger.price_tokens(model, input_tokens, output_tokens, thinking_tokens)
    ledger.record(
        CallRecord(
            stage=stage,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            search_queries=search_queries,
            cost_usd=cost,
        )
    )

    text = getattr(response, "text", None) or ""
    if use_cache:
        cache_put(
            key,
            {
                "text": text,
                "sources": [{"url": s.url, "title": s.title} for s in sources],
                "search_queries_executed": search_queries,
            },
        )

    return GenerateResult(
        text=text, cache_hit=False, sources=sources, search_queries_executed=search_queries
    )
