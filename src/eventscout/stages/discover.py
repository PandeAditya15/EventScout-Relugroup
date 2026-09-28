"""Grounded-search discovery stage: one call per category, using Gemini's
google_search tool, capturing the cited sources and executed search-query count
needed downstream for extraction and for the cost ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from google.genai import types

from eventscout.config import DISCOVERY_MODEL
from eventscout.cost import CostLedger
from eventscout.llm import GeminiClient, Source, generate
from eventscout.models import EventCategory
from eventscout.prompts import CATEGORY_FOCUS, DISCOVERY_PROMPT_TEMPLATE


@dataclass
class DiscoveryResult:
    category: EventCategory
    text: str
    sources: list[Source] = field(default_factory=list)
    search_queries_executed: int = 0


def discover_category(
    client: GeminiClient,
    *,
    category: EventCategory,
    city: str,
    country_code: str,
    month: str,
    ledger: CostLedger,
    use_cache: bool = True,
) -> DiscoveryResult:
    """Run one grounded-search call for a single event category."""
    prompt = DISCOVERY_PROMPT_TEMPLATE.format(
        city=city,
        country_code=country_code,
        month=month,
        category_focus=CATEGORY_FOCUS[category],
    )
    config = {
        "tools": [types.Tool(google_search=types.GoogleSearch())],
        # Left unconfigured, gemini-3.5-flash defaults to a higher thinking
        # level; since output tokens (including invisible thinking tokens)
        # are billed at this model's $9/1M rate -- the priciest in the
        # pipeline -- that made a 6-category run cost ~$0.42 instead of the
        # ~$0.06 estimated. LOW (not MINIMAL, like extract/enrich) keeps some
        # reasoning for search synthesis while capping the cost. See
        # docs/decisions.md.
        "thinking_config": types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    }

    result = generate(
        client,
        model=DISCOVERY_MODEL,
        prompt=prompt,
        config=config,
        stage="discover",
        ledger=ledger,
        use_cache=use_cache,
    )

    return DiscoveryResult(
        category=category,
        text=result.text,
        sources=result.sources,
        search_queries_executed=result.search_queries_executed,
    )
