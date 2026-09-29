"""OpenLigaDB connector: Munich football clubs' home matches. Free, no API key.

Deterministic, not LLM-based -- returns list[RawEvent] directly, cached like
everything else that hits the network. Skippable: if the request fails, this
returns [] with a warning rather than raising, so the pipeline still runs.

Verified live (2026-09-29) against https://api.openligadb.de: only FC Bayern
München appears in bl1/bl2/bl3 for the 2026 season among Munich clubs, and
`team1` is the home team (confirmed with the user against real fixture data --
no OpenLigaDB doc states this explicitly). See docs/decisions.md.

Licence: OpenLigaDB data is under the Open Database License (ODbL), which
requires attribution -- see export.py's ATTRIBUTION_BY_SOURCE.
"""

from __future__ import annotations

from datetime import date

import httpx

from eventscout.cache import cache_key
from eventscout.cache import get as cache_get
from eventscout.cache import put as cache_put
from eventscout.config import MUNICH_CLUB_STADIUMS
from eventscout.models import AttendanceBasis, DiscoverySource, EventCategory, RawEvent, SourceRef

BASE_URL = "https://api.openligadb.de"
LEAGUE_SHORTCUT = "bl1"  # the only shortcut confirmed to list a Munich club (2026 season)


def fetch_munich_home_matches(
    *, season: int, month: str, http_client: httpx.Client, use_cache: bool = True
) -> list[RawEvent]:
    """Munich clubs' home matches overlapping `month` (YYYY-MM), for `season`
    (the year the season starts in, e.g. 2026 for 2026/27)."""
    url = f"{BASE_URL}/getmatchdata/{LEAGUE_SHORTCUT}/{season}"
    matches = _fetch_matches(url, http_client, use_cache=use_cache)

    events = []
    for match in matches:
        home_team = match["team1"]["teamName"]
        stadium = MUNICH_CLUB_STADIUMS.get(home_team)
        if stadium is None:
            continue  # not a Munich club's home match
        if match["matchDateTimeUTC"][:7] != month:
            continue
        events.append(_to_raw_event(match, home_team, stadium, source_url=url))
    return events


def _fetch_matches(url: str, http_client: httpx.Client, *, use_cache: bool) -> list[dict]:
    key = cache_key("openligadb", url, {})
    if use_cache:
        cached = cache_get(key)
        if cached is not None:
            return cached["matches"]

    try:
        response = http_client.get(url, timeout=10.0)
        response.raise_for_status()
        matches = response.json()
    except httpx.HTTPError as exc:
        print(f"Warning: OpenLigaDB request failed, skipping this source: {exc}")
        return []

    if use_cache:
        cache_put(key, {"matches": matches})
    return matches


def _to_raw_event(match: dict, home_team: str, stadium: dict, *, source_url: str) -> RawEvent:
    away_team = match["team2"]["teamName"]
    match_date = date.fromisoformat(match["matchDateTimeUTC"][:10])
    return RawEvent(
        name=f"{home_team} vs {away_team}",
        category=EventCategory.SPORTS,
        start_date=match_date,
        end_date=match_date,
        venue_name=stadium["stadium_name"],
        # Every entry in MUNICH_CLUB_STADIUMS is, by construction, a Munich
        # club's home stadium -- not a guess -- but clean.py's location
        # filter matches on venue text, and "Allianz Arena" alone doesn't
        # contain "Munich", so without this every match gets dropped as
        # wrong_location (found live -- see docs/decisions.md).
        venue_district="Munich",
        attendance_high=stadium["capacity"],
        attendance_basis=AttendanceBasis.ESTIMATED,
        attendance_source_url=stadium["capacity_source_url"],
        sources=[SourceRef(url=source_url, title="OpenLigaDB")],
        discovered_via=[DiscoverySource.OPENLIGADB_API],
    )
