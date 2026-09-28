"""Extraction stage: turns one discovery call's text into structured RawEvents.

No tools, CHEAP_MODEL, structured JSON output. Thinking is set to MINIMAL --
the lowest level Gemini 3.5-gen models support (they use `thinking_level`,
not the older `thinking_budget` parameter, which caused a live 400
INVALID_ARGUMENT when tried first; see docs/decisions.md) -- since extraction
is parsing, not reasoning, and doesn't need deep thinking.
"""

from __future__ import annotations

import json
from datetime import date

from google.genai import types

from eventscout.config import CHEAP_MODEL
from eventscout.cost import CostLedger
from eventscout.llm import GeminiClient, Source, generate
from eventscout.llm_schemas import ExtractedEvent
from eventscout.models import DiscoverySource, EventCategory, RawEvent, SourceRef
from eventscout.prompts import EXTRACTION_PROMPT_TEMPLATE


def extract_events(
    client: GeminiClient,
    *,
    text: str,
    sources: list[Source],
    category: EventCategory,
    ledger: CostLedger,
    use_cache: bool = True,
) -> list[RawEvent]:
    """Extract structured events from one discovery call's text and sources."""
    if not text.strip() or not sources:
        return []

    numbered_sources = "\n".join(f"{i + 1}. {s.url}" for i, s in enumerate(sources))
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(text=text, numbered_sources=numbered_sources)

    config = {
        "response_mime_type": "application/json",
        "response_schema": list[ExtractedEvent],
        "thinking_config": types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
    }

    result = generate(
        client,
        model=CHEAP_MODEL,
        prompt=prompt,
        config=config,
        stage="extract",
        ledger=ledger,
        use_cache=use_cache,
    )

    extracted = _parse_extracted_events(result.text)
    # An event with no cited source number is dropped here rather than later,
    # per the brief: every candidate must cite source numbers from the list.
    return [_to_raw_event(e, sources, category) for e in extracted if e.source_numbers]


def _parse_extracted_events(text: str) -> list[ExtractedEvent]:
    """Malformed model output yields no events rather than raising -- one bad
    extraction call shouldn't crash the whole run."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [ExtractedEvent.model_validate(item) for item in payload]


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_raw_event(
    extracted: ExtractedEvent, sources: list[Source], category: EventCategory
) -> RawEvent:
    cited = [
        SourceRef(url=sources[i - 1].url, title=sources[i - 1].title)
        for i in extracted.source_numbers
        if 1 <= i <= len(sources)
    ]
    return RawEvent(
        name=extracted.name,
        name_local=extracted.name_local,
        category=category,
        subcategory=extracted.subcategory,
        description=extracted.description,
        start_date=_parse_iso_date(extracted.start_date),
        end_date=_parse_iso_date(extracted.end_date),
        venue_name=extracted.venue_name,
        venue_address=extracted.venue_address,
        venue_district=extracted.venue_district,
        organizer=extracted.organizer,
        url=extracted.url,
        is_free=extracted.is_free,
        price_note=extracted.price_note,
        attendance_value=extracted.attendance_value,
        attendance_basis=extracted.attendance_basis,
        sources=cited,
        discovered_via=[DiscoverySource.GEMINI_GROUNDED_SEARCH],
    )
