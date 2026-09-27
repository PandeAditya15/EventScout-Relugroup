"""Typer CLI entry point.

`smoke-test` makes one live call (listing models) to confirm the API key works
and to let the user pick real model IDs from what's actually available — it
must never be run without the user's go-ahead first, per the project brief.
"""

from __future__ import annotations

import json

import typer
from google import genai

from eventscout.config import GEMINI_API_KEY, SCHEMA_DIR
from eventscout.models import EventScoutOutput

app = typer.Typer(help="Find real-world events in a city/month, with sourced evidence.")


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


@app.command(name="export-schema")
def export_schema() -> None:
    """Write the current output JSON Schema to schema/events.schema.json."""
    schema = EventScoutOutput.model_json_schema()
    path = SCHEMA_DIR / "events.schema.json"
    path.write_text(json.dumps(schema, indent=2))
    typer.echo(f"Wrote {path}")


if __name__ == "__main__":
    app()
