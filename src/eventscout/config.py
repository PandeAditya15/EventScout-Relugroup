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
# TODO(verify): fill in after `eventscout smoke-test` lists the models this
# API key can actually use. Do not fill these in from memory.

DISCOVERY_MODEL = "TODO(verify)"  # Flash tier; used with the google_search tool
CHEAP_MODEL = "TODO(verify)"  # Flash-Lite tier; used for structured extraction/enrichment

# --- Pricing -------------------------------------------------------------
# TODO(verify): every value here must be confirmed on the official Gemini API
# pricing page and shown to the user before it drives any cost estimate or
# budget check. All values below are placeholders, not real prices.

PRICING: dict = {
    # USD per 1,000 executed grounded-search queries.
    "grounded_search_per_1k_queries_usd": None,  # TODO(verify); brief cites ~$14/1k, unconfirmed
    # USD per 1,000,000 tokens, keyed by model then token type.
    "tokens_per_1m_usd": {
        # "<model-id>": {"input": None, "output": None, "thinking": None},
    },
}

DEFAULT_MAX_COST_USD = 2.0
