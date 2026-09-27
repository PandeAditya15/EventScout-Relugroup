"""Shared test fakes for anything that calls the Gemini wrapper.

No test in this suite makes a network call or needs a real API key --
FakeGeminiClient stands in for google.genai's Client.models everywhere.
"""

from types import SimpleNamespace

import pytest

import eventscout.cache as cache_module


def make_response(text: str, input_tokens=10, output_tokens=5, thinking_tokens=0):
    usage = SimpleNamespace(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
        thoughts_token_count=thinking_tokens,
    )
    return SimpleNamespace(text=text, usage_metadata=usage, candidates=None)


def make_grounded_response(text: str, urls: list[str]):
    chunks = [
        SimpleNamespace(web=SimpleNamespace(uri=url, title=f"title for {url}")) for url in urls
    ]
    metadata = SimpleNamespace(grounding_chunks=chunks, web_search_queries=["q1", "q2"])
    candidate = SimpleNamespace(grounding_metadata=metadata)
    usage = SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0)
    return SimpleNamespace(text=text, usage_metadata=usage, candidates=[candidate])


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
