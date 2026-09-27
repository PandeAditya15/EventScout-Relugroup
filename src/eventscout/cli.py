"""Typer CLI entry point.

`smoke-test` makes one live call (listing models) to confirm the API key works
and to let the user pick real model IDs from what's actually available — it
must never be run without the user's go-ahead first, per the project brief.
"""

from __future__ import annotations

import datetime as dt
import json

import typer
from google import genai

from eventscout.config import (
    CHEAP_MODEL,
    DATA_INTERIM_DIR,
    DEFAULT_MAX_COST_USD,
    DISCOVERY_MODEL,
    GEMINI_API_KEY,
    SCHEMA_DIR,
)
from eventscout.cost import BudgetExceededError, CostLedger
from eventscout.models import EventCategory, EventScoutOutput
from eventscout.stages.discover import discover_category
from eventscout.stages.extract import extract_events

app = typer.Typer(help="Find real-world events in a city/month, with sourced evidence.")

DISCOVERABLE_CATEGORIES = [c for c in EventCategory if c != EventCategory.OTHER]


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


@app.command()
def run(
    city: str = typer.Option("Munich", help="Target city"),
    country: str = typer.Option("DE", help="ISO 3166-1 alpha-2 country code"),
    month: str = typer.Option("2026-10", help="Target month, YYYY-MM"),
    categories: str | None = typer.Option(
        None, help="Comma-separated categories to discover; defaults to all"
    ),
    max_cost_usd: float = typer.Option(
        DEFAULT_MAX_COST_USD, "--max-cost-usd", help="Abort before starting a call once spent"
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable the disk cache"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print planned calls and exit; makes no API calls"
    ),
) -> None:
    """Discover and extract events for a city/month.

    Only discover + extract exist so far (clean/enrich/export are later
    milestones), so this writes the raw, undeduped events it finds rather than
    the final schema-validated output.
    """
    selected = _parse_categories(categories)

    if dry_run:
        typer.echo(f"Would run for {city}, {country}, {month}")
        typer.echo(f"Categories ({len(selected)}): {', '.join(c.value for c in selected)}")
        typer.echo(f"Discovery model: {DISCOVERY_MODEL}  |  Extraction model: {CHEAP_MODEL}")
        typer.echo(f"Planned calls: {len(selected)} discover + up to {len(selected)} extract")
        typer.echo("No API calls made (--dry-run).")
        return

    if not GEMINI_API_KEY:
        typer.echo("GEMINI_API_KEY is not set in .env. Aborting.", err=True)
        raise typer.Exit(code=1)

    client = genai.Client(api_key=GEMINI_API_KEY)
    ledger = CostLedger(max_cost_usd=max_cost_usd)
    all_events = []

    try:
        for category in selected:
            typer.echo(f"Discovering: {category.value}...")
            discovery = discover_category(
                client,
                category=category,
                city=city,
                country_code=country,
                month=month,
                ledger=ledger,
                use_cache=not no_cache,
            )
            events = extract_events(
                client,
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

    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = DATA_INTERIM_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "raw_events.json"
    out_path.write_text(json.dumps([e.model_dump(mode="json") for e in all_events], indent=2))

    typer.echo(f"\nWrote {len(all_events)} raw event(s) to {out_path}")
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
