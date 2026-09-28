"""All LLM prompts, as named constants.

One discovery call is made per category (see stages/discover.py); the same
template is reused with a category-specific focus line rather than six
near-duplicate prompt strings.
"""

from eventscout.models import EventCategory

CATEGORY_FOCUS: dict[EventCategory, str] = {
    EventCategory.TRADE_FAIR_CONGRESS: (
        "large trade fairs, industry congresses, and B2B exhibitions"
    ),
    EventCategory.TECH_BUSINESS_CONFERENCE: (
        "technology and business conferences, summits, and startup events"
    ),
    EventCategory.SPORTS: "major sports fixtures, tournaments, and matches",
    EventCategory.MUSIC_CONCERT: "concerts and large music performances",
    EventCategory.FESTIVAL_CULTURE: ("public festivals, cultural celebrations, and civic events"),
    EventCategory.ACADEMIC_COMMUNITY: (
        "academic conferences, university events, and community gatherings"
    ),
}

DISCOVERY_PROMPT_TEMPLATE = """\
You are researching real-world events in {city}, {country_code} taking place \
during {month}. Include events that start before or end after this month, as \
long as they overlap it.

Focus category: {category_focus}.

Use Google Search to find real events, and report for each one:
- name (and local-language name, if different)
- a short description of what it is
- start date and end date (ISO 8601, YYYY-MM-DD), if known
- venue name and address or district, if known
- organizer, if known
- approximate attendance or participant numbers, if known, and whether that \
figure is officially reported or your own estimate
- the URL(s) you found this information from

Only report events you found real evidence for. Never invent or guess an \
event, date, venue, or number. If a detail is unknown, say so explicitly \
instead of filling it in.
"""

EXTRACTION_PROMPT_TEMPLATE = """\
Below is text describing events, followed by a numbered list of the source \
URLs it was drawn from.

Extract every distinct event mentioned into structured form, following these \
rules:
- Use only facts stated in the text. Never invent or infer a fact that isn't \
there -- if a field is unknown, output null for it.
- For every event, list the numbers (from the numbered source list) of every \
source that supports it, in `source_numbers`. An event with no supporting \
source number will be discarded.
- Do not merge distinct events into one, and do not split one event into \
several.

Text:
{text}

Numbered sources:
{numbered_sources}
"""

ENRICHMENT_PROMPT_TEMPLATE = """\
Below is a numbered list of real-world events. For each one, infer:

1. Its likely audience: type (b2b, b2c, or mixed), likely segments, \
industries, interests, and languages of attendees.
2. Where attendees likely come from: one or more regions, each with likely \
country codes (ISO 3166-1 alpha-2), a scope (local, regional, national, or \
international), and a rough share (high, medium, or low), plus an overall \
international_share.

Base every inference only on the event's type, scale, and the facts given \
below -- not on outside knowledge of the specific event. These are estimates, \
not facts, so:
- Give a confidence level (high, medium, or low) for the audience inference \
and separately for the geographic-origin inference.
- Give a one-sentence rationale for each, referencing the event facts that \
led to it (e.g. "a free public folk festival draws a broad local audience").

Return one result per event, using `event_number` to match the numbering \
below.

Events:
{numbered_events}
"""
