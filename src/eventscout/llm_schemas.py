"""Small, flat schemas for Gemini structured output.

Kept deliberately flat (no nested objects, no multi-type unions besides
Optional/null) per the project brief, since structured output support for
arbitrary JSON Schema features is inconsistent. Dates are plain strings, not
`date`, so a malformed model output fails a parse step in extract.py rather
than an opaque schema-validation error inside the API call.
"""

from pydantic import BaseModel, Field

from eventscout.models import AttendanceBasis


class ExtractedEvent(BaseModel):
    """One event as pulled from discovery text. Category is not extracted here
    -- it's already known from which per-category discovery call produced the
    source text, so extract.py attaches it directly to the RawEvent."""

    name: str
    name_local: str | None = None
    subcategory: str | None = None
    description: str | None = None

    start_date: str | None = None  # ISO 8601 YYYY-MM-DD, parsed in extract.py
    end_date: str | None = None

    venue_name: str | None = None
    venue_address: str | None = None
    venue_district: str | None = None

    organizer: str | None = None
    url: str | None = None
    is_free: bool | None = None
    price_note: str | None = None

    attendance_value: int | None = None
    attendance_basis: AttendanceBasis | None = None

    source_numbers: list[int] = Field(default_factory=list)
