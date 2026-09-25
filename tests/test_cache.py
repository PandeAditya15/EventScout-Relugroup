"""Tests for the disk cache. Uses a temp dir (monkeypatched) so we never touch cache/."""

import eventscout.cache as cache_module


def test_cache_key_is_stable_for_same_input():
    k1 = cache_module.cache_key("model-a", "prompt", {"temperature": 0})
    k2 = cache_module.cache_key("model-a", "prompt", {"temperature": 0})
    assert k1 == k2


def test_cache_key_differs_for_different_input():
    k1 = cache_module.cache_key("model-a", "prompt", {})
    k2 = cache_module.cache_key("model-b", "prompt", {})
    assert k1 != k2


def test_get_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path)
    assert cache_module.get("nonexistent-key") is None


def test_put_then_get_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path)
    key = cache_module.cache_key("model-a", "prompt", {})
    cache_module.put(key, {"text": "hello"})
    assert cache_module.get(key) == {"text": "hello"}
