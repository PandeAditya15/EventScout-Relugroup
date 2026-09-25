"""CLI tests. `smoke-test` is not exercised here — it makes a real, live Gemini
call and must only run with the user's explicit go-ahead (see project brief).
"""

import json

from typer.testing import CliRunner

import eventscout.cli as cli_module
from eventscout.cli import app

runner = CliRunner()


def test_export_schema_writes_valid_json_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "SCHEMA_DIR", tmp_path)

    result = runner.invoke(app, ["export-schema"])

    assert result.exit_code == 0
    written = tmp_path / "events.schema.json"
    assert written.exists()
    schema = json.loads(written.read_text())
    assert schema["title"] == "EventScoutOutput"
    assert "events" in schema["properties"]


def test_smoke_test_aborts_without_api_key(monkeypatch):
    monkeypatch.setattr(cli_module, "GEMINI_API_KEY", None)

    result = runner.invoke(app, ["smoke-test"])

    assert result.exit_code == 1
