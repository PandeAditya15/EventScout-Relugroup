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
#
# gemini-2.5-flash/-flash-lite were tried first (listed by smoke-test) but a
# live call to gemini-2.5-flash returned 404 "no longer available to new
# users" -- 2.5-generation models are dead for this key despite being listed.
# Switched to the 3.5 generation, which the API's own error message pointed
# to. gemini-flash-lite-latest was considered for CHEAP_MODEL but rejected:
# it's an alias with no listed price on the pricing page, so its cost can't
# be verified -- see docs/decisions.md.

DISCOVERY_MODEL = "gemini-3.5-flash"  # Flash tier; used with the google_search tool
CHEAP_MODEL = "gemini-3.5-flash-lite"  # Flash-Lite tier; used for structured extraction/enrichment

# --- Pricing -------------------------------------------------------------
# Source: https://ai.google.dev/gemini-api/docs/pricing, Paid tier / Standard,
# confirmed 2026-09-27 for gemini-3.5-flash / gemini-3.5-flash-lite. Text
# input rates only (no audio calls in this pipeline). Thinking tokens have no
# separate rate on that page -- Google bills them at the output rate, so
# cost.py folds thoughts_token_count into the output token count.
#
# Grounded search on Gemini 3.x models: 5,000 requests/month free (shared
# across all Gemini 3.x models), then $14 per 1,000 requests. The rate below
# prices every query as paid and ignores the free monthly allowance -- a
# deliberate over-estimate, since the ledger's job is to cap spend, not track
# a shared cross-model monthly quota.

PRICING: dict = {
    "grounded_search_per_1k_queries_usd": 14.0,
    "tokens_per_1m_usd": {
        "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
        "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    },
}

DEFAULT_MAX_COST_USD = 2.0

# --- OpenLigaDB club/stadium mapping ---------------------------------------
# Confirmed 2026-09-29 with the user, not filled in from memory. Verified live
# against getavailableteams for bl1/bl2/bl3 (season 2026): only FC Bayern
# München appears among Munich clubs -- see docs/decisions.md.

MUNICH_CLUB_STADIUMS: dict[str, dict] = {
    "FC Bayern München": {
        "stadium_name": "Allianz Arena",
        "capacity": 75_000,
        "capacity_source_url": "https://www.allianz-arena.com/en/",
    },
}
