"""Enrichment stage: infers audience and geographic origin for cleaned events.

CHEAP_MODEL, structured output, no tools, batched ~5 events per call to keep
prompts small. These fields are always inferences, never facts -- export.py
labels them as such in `inferred_fields` regardless of confidence level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from google.genai import types

from eventscout.config import CHEAP_MODEL
from eventscout.cost import CostLedger
from eventscout.llm import GeminiClient, generate
from eventscout.llm_schemas import EnrichedEvent
from eventscout.models import EventAudience, EventGeographicOrigin, GeographicOrigin, RawEvent
from eventscout.prompts import ENRICHMENT_PROMPT_TEMPLATE

BATCH_SIZE = 5


@dataclass
class EnrichedRawEvent:
    raw: RawEvent
    audience: EventAudience
    geographic_origin: EventGeographicOrigin


def enrich_events(
    client: GeminiClient,
    events: list[RawEvent],
    *,
    ledger: CostLedger,
    use_cache: bool = True,
) -> list[EnrichedRawEvent]:
    """Enrich all events, batching BATCH_SIZE at a time."""
    enriched: list[EnrichedRawEvent] = []
    for start in range(0, len(events), BATCH_SIZE):
        batch = events[start : start + BATCH_SIZE]
        enriched.extend(_enrich_batch(client, batch, ledger=ledger, use_cache=use_cache))
    return enriched


def _enrich_batch(
    client: GeminiClient,
    batch: list[RawEvent],
    *,
    ledger: CostLedger,
    use_cache: bool,
) -> list[EnrichedRawEvent]:
    if not batch:
        return []

    numbered_events = "\n".join(f"{i + 1}. {_describe(event)}" for i, event in enumerate(batch))
    prompt = ENRICHMENT_PROMPT_TEMPLATE.format(numbered_events=numbered_events)

    config = {
        "response_mime_type": "application/json",
        "response_schema": list[EnrichedEvent],
        "thinking_config": types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
    }

    result = generate(
        client,
        model=CHEAP_MODEL,
        prompt=prompt,
        config=config,
        stage="enrich",
        ledger=ledger,
        use_cache=use_cache,
    )

    by_number = _parse_enriched_events(result.text)
    results = []
    for i, event in enumerate(batch):
        enriched = by_number.get(i + 1)
        if enriched is None:
            results.append(
                EnrichedRawEvent(
                    raw=event,
                    audience=_fallback_audience(),
                    geographic_origin=_fallback_geographic_origin(),
                )
            )
        else:
            results.append(
                EnrichedRawEvent(
                    raw=event,
                    audience=_to_audience(enriched),
                    geographic_origin=_to_geographic_origin(enriched),
                )
            )
    return results


def _describe(event: RawEvent) -> str:
    facts = [
        f"name: {event.name}",
        f"category: {event.category.value if event.category else 'unknown'}",
        f"dates: {event.start_date} to {event.end_date}",
        f"venue: {event.venue_name or 'unknown'}",
        f"attendance: {event.attendance_value or 'unknown'} "
        f"({event.attendance_basis or 'unknown'})",
        f"description: {event.description or 'none'}",
    ]
    return "; ".join(facts)


def _parse_enriched_events(text: str) -> dict[int, EnrichedEvent]:
    """Malformed model output yields no enrichment for that batch rather than
    raising -- callers fall back to a low-confidence default per event."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    events = [EnrichedEvent.model_validate(item) for item in payload]
    return {e.event_number: e for e in events}


def _to_audience(enriched: EnrichedEvent) -> EventAudience:
    return EventAudience(
        type=enriched.audience_type,
        segments=enriched.audience_segments,
        industries=enriched.audience_industries,
        interests=enriched.audience_interests,
        languages=enriched.audience_languages,
        confidence=enriched.audience_confidence,
        rationale=enriched.audience_rationale,
    )


def _to_geographic_origin(enriched: EnrichedEvent) -> EventGeographicOrigin:
    return EventGeographicOrigin(
        primary=[
            GeographicOrigin(
                region=item.region,
                country_codes=item.country_codes,
                scope=item.scope,
                share=item.share,
            )
            for item in enriched.geographic_origin_primary
        ],
        international_share=enriched.geographic_origin_international_share,
        confidence=enriched.geographic_origin_confidence,
        rationale=enriched.geographic_origin_rationale,
    )


def _fallback_audience() -> EventAudience:
    return EventAudience(
        type="mixed",
        confidence="low",
        rationale="Enrichment call failed or omitted this event; no inference available.",
    )


def _fallback_geographic_origin() -> EventGeographicOrigin:
    return EventGeographicOrigin(
        confidence="low",
        rationale="Enrichment call failed or omitted this event; no inference available.",
    )
