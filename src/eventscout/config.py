"""Runtime configuration: env-derived settings, paths, and model/pricing placeholders.

Model IDs and prices are never guessed. They stay as TODO(verify) until confirmed
against the installed SDK (for model IDs, via `eventscout smoke-test`) or the
official Gemini pricing page (for prices), per the project's verification rules.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "cache"
DATA_INTERIM_DIR = REPO_ROOT / "data" / "interim"
SCHEMA_DIR = REPO_ROOT / "schema"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
DATA_INTERIM_DIR.mkdir(parents=True, exist_ok=True)

# --- Secrets (from .env, never hard-coded) ------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY")
NOMINATIM_CONTACT_EMAIL = os.environ.get("NOMINATIM_CONTACT_EMAIL")
DATABASE_URL = os.environ.get("DATABASE_URL")

# --- Models --------------------------------------------------------------
# Confirmed via `eventscout smoke-test` (2026-09-27) against the models this
# API key can actually use, and picked by the user from that list.

DISCOVERY_MODEL = "gemini-2.5-flash"  # Flash tier; used with the google_search tool
CHEAP_MODEL = "gemini-2.5-flash-lite"  # Flash-Lite tier; used for structured extraction/enrichment

# --- Pricing -------------------------------------------------------------
# Source: https://ai.google.dev/gemini-api/docs/pricing, Paid tier / Standard,
# confirmed 2026-09-27. Text/image/video input rates only (no audio calls in
# this pipeline). Thinking tokens have no separate rate on that page -- Google
# bills them at the output rate, so cost.py folds thoughts_token_count into
# the output token count rather than pricing it separately.
#
# Grounded search: 1,500 requests/day free (shared across Flash + Flash-Lite),
# then $35 per 1,000 requests. The rate below prices every query as paid and
# ignores the free daily allowance -- a deliberate over-estimate, since the
# ledger's job is to cap spend, not track a shared daily quota.

PRICING: dict = {
    "grounded_search_per_1k_queries_usd": 35.0,
    "tokens_per_1m_usd": {
        "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
        "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    },
}

DEFAULT_MAX_COST_USD = 2.0
