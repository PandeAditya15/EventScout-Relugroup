"""Typer CLI entry point.

`smoke-test` makes one live call (listing models) to confirm the API key works
and to let the user pick real model IDs from what's actually available — it
must never be run without the user's go-ahead first, per the project brief.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json

import httpx
import typer
from google import genai

from eventscout.config import (
    CHEAP_MODEL,
    DATA_INTERIM_DIR,
    DEFAULT_MAX_COST_USD,
    DISCOVERY_MODEL,
    GEMINI_API_KEY,
    REPO_ROOT,
    SCHEMA_DIR,
)
from eventscout.connectors.openligadb import fetch_munich_home_matches
from eventscout.cost import BudgetExceededError, CostLedger
from eventscout.models import EventCategory, EventScoutOutput
from eventscout.stages.clean import clean_events
from eventscout.stages.discover import discover_category
from eventscout.stages.enrich import enrich_events
from eventscout.stages.export import build_output
from eventscout.stages.extract import extract_events

app = typer.Typer(help="Find real-world events in a city/month, with sourced evidence.")

DISCOVERABLE_CATEGORIES = [c for c in EventCategory if c != EventCategory.OTHER]
AVAILABLE_SOURCES = {"gemini", "openligadb"}


@app.command(name="smoke-test")
def smoke_test() -> None:
    """List the Gemini models available to this API key (one live call).

    Model IDs are never hard-coded from memory (see config.py) — this command
    is how the real DISCOVERY_MODEL/CHEAP_MODEL values get chosen and confirmed.
    """
    if not GEMINI_API_KEY:
        typer.echo("GEMINI_API_KEY is not set in .env. Aborting.", err=True)
        raise typer.Exit(code=1)

    client = genai.Client(api_key=GEMINI_API_KEY)

    typer.echo("Available models:")
    for model in client.models.list():
        typer.echo(f"  {model.name}  (display_name={model.display_name})")


def _parse_categories(categories: str | None) -> list[EventCategory]:
    if not categories:
        return DISCOVERABLE_CATEGORIES
    return [EventCategory(name.strip()) for name in categories.split(",") if name.strip()]


def _parse_sources(sources: str) -> set[str]:
    requested = {name.strip() for name in sources.split(",") if name.strip()}
    unknown = requested - AVAILABLE_SOURCES
    if unknown:
        raise typer.BadParameter(f"Unknown source(s): {', '.join(sorted(unknown))}")
    return requested


def _bundesliga_season_for_month(year: int, month_num: int) -> int:
    """The Bundesliga season starting year for OpenLigaDB (brief: '2026 means
    2026/27'). The season runs roughly August-May, so a month before August
    belongs to the season that started the previous year. Not stated
    explicitly in the brief; a reasonable judgment call, not a guess about
    OpenLigaDB's own data -- see docs/decisions.md."""
    return year if month_num >= 8 else year - 1


@app.command()
def run(
    city: str = typer.Option("Munich", help="Target city"),
    country: str = typer.Option("DE", help="ISO 3166-1 alpha-2 country code"),
    month: str = typer.Option("2026-10", help="Target month, YYYY-MM"),
    categories: str | None = typer.Option(
        None, help="Comma-separated categories to discover; defaults to all"
    ),
    sources: str = typer.Option(
        "gemini,openligadb", "--sources", help="Comma-separated sources to use"
    ),
    max_cost_usd: float = typer.Option(
        DEFAULT_MAX_COST_USD, "--max-cost-usd", help="Abort before starting a call once spent"
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable the disk cache"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print planned calls and exit; makes no API calls"
    ),
) -> None:
    """Discover, extract, clean, enrich, and export events for a city/month.

    Writes the final schema-validated output to events_<mon>_<year>.json at
    the repo root.
    """
    selected = _parse_categories(categories)
    selected_sources = _parse_sources(sources)
    year, month_num = (int(part) for part in month.split("-"))

    if dry_run:
        typer.echo(f"Would run for {city}, {country}, {month}")
        typer.echo(f"Sources: {', '.join(sorted(selected_sources))}")
        typer.echo(f"Categories ({len(selected)}): {', '.join(c.value for c in selected)}")
        typer.echo(f"Discovery model: {DISCOVERY_MODEL}  |  Extraction/enrich model: {CHEAP_MODEL}")
        typer.echo(
            f"Planned calls: {len(selected)} discover + up to {len(selected)} extract "
            "+ 1 enrich call per 5 surviving events (exact count depends on how many "
            "events discovery/clean actually produce)"
        )
        typer.echo("No API calls made (--dry-run).")
        return

    if not GEMINI_API_KEY:
        typer.echo("GEMINI_API_KEY is not set in .env. Aborting.", err=True)
        raise typer.Exit(code=1)

    # `client` must stay referenced for the run's lifetime: discarding it right
    # after taking `.models` lets its underlying HTTP client get garbage
    # collected (and closed) before any request fires.
    client = genai.Client(api_key=GEMINI_API_KEY)
    models_client = client.models
    ledger = CostLedger(max_cost_usd=max_cost_usd)
    all_events = []

    if "openligadb" in selected_sources:
        season = _bundesliga_season_for_month(year, month_num)
        typer.echo(f"Fetching OpenLigaDB (season {season})...")
        with httpx.Client() as ligadb_client:
            openligadb_events = fetch_munich_home_matches(
                season=season, month=month, http_client=ligadb_client, use_cache=not no_cache
            )
        typer.echo(f"  found {len(openligadb_events)} home match(es)")
        all_events.extend(openligadb_events)

    if "gemini" not in selected_sources:
        selected = []

    try:
        for category in selected:
            typer.echo(f"Discovering: {category.value}...")
            discovery = discover_category(
                models_client,
                category=category,
                city=city,
                country_code=country,
                month=month,
                ledger=ledger,
                use_cache=not no_cache,
            )
            events = extract_events(
                models_client,
                text=discovery.text,
                sources=discovery.sources,
                category=category,
                ledger=ledger,
                use_cache=not no_cache,
            )
            typer.echo(f"  found {len(events)} event(s) from {len(discovery.sources)} source(s)")
            all_events.extend(events)
    except BudgetExceededError as exc:
        typer.echo(f"\nStopped: {exc}", err=True)

    typer.echo(f"\nCleaning {len(all_events)} raw event(s)...")
    with httpx.Client() as http_client:
        cleaned = clean_events(all_events, month=month, city=city, http_client=http_client)
    typer.echo(f"  dropped: {cleaned.dropped_by_reason}")

    typer.echo(f"\nEnriching {len(cleaned.events)} event(s)...")
    try:
        enriched = enrich_events(
            models_client, cleaned.events, ledger=ledger, use_cache=not no_cache
        )
    except BudgetExceededError as exc:
        typer.echo(f"\nStopped during enrichment: {exc}", err=True)
        enriched = []

    output = build_output(
        enriched,
        city=city,
        country_code=country,
        month=month,
        models={"discovery": DISCOVERY_MODEL, "cheap": CHEAP_MODEL},
        ledger=ledger,
        dropped_by_reason=cleaned.dropped_by_reason,
    )

    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    interim_path = DATA_INTERIM_DIR / run_id / "output.json"
    interim_path.parent.mkdir(parents=True, exist_ok=True)
    interim_path.write_text(output.model_dump_json(indent=2))

    month_abbr = calendar.month_abbr[month_num].lower()
    final_path = REPO_ROOT / f"events_{month_abbr}_{year}.json"
    final_path.write_text(output.model_dump_json(indent=2))

    typer.echo(f"\nWrote {output.stats.event_count} final event(s) to {final_path}")
    typer.echo(ledger.summary())


@app.command(name="export-schema")
def export_schema() -> None:
    """Write the current output JSON Schema to schema/events.schema.json."""
    schema = EventScoutOutput.model_json_schema()
    path = SCHEMA_DIR / "events.schema.json"
    path.write_text(json.dumps(schema, indent=2))
    typer.echo(f"Wrote {path}")


if __name__ == "__main__":
    app()
