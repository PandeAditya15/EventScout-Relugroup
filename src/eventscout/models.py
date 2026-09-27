"""Final output schema (Event, EventScoutOutput) and the pipeline's shared RawEvent model.

Every stage after discovery/extraction works with RawEvent, regardless of which
source produced it. `export.py` turns validated, deduped RawEvents into the final
Event objects defined here.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


# --- Enums ---------------------------------------------------------------


class EventCategory(StrEnum):
    TRADE_FAIR_CONGRESS = "trade_fair_congress"
    TECH_BUSINESS_CONFERENCE = "tech_business_conference"
    SPORTS = "sports"
    MUSIC_CONCERT = "music_concert"
    FESTIVAL_CULTURE = "festival_culture"
    ACADEMIC_COMMUNITY = "academic_community"
    OTHER = "other"


class AttendanceBasis(StrEnum):
    REPORTED = "reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ScaleTier(StrEnum):
    LOCAL = "local"
    REGIONAL = "regional"
    NATIONAL = "national"
    INTERNATIONAL = "international"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DiscoverySource(StrEnum):
    GEMINI_GROUNDED_SEARCH = "gemini_grounded_search"
    OPENLIGADB_API = "openligadb_api"
    TICKETMASTER_API = "ticketmaster_api"


class AudienceType(StrEnum):
    B2B = "b2b"
    B2C = "b2c"
    MIXED = "mixed"


class GeoScope(StrEnum):
    LOCAL = "local"
    REGIONAL = "regional"
    NATIONAL = "national"
    INTERNATIONAL = "international"


# --- Shared sub-models -----------------------------------------------------


class SourceRef(BaseModel):
    url: str
    title: str | None = None
    publisher_domain: str | None = None
    retrieved_at: datetime | None = None


# --- RawEvent: the shared pipeline intermediate model -----------------------


class RawEvent(BaseModel):
    """One event as produced by any single source, before cross-source merge.

    `clean.py` fuzzy-dedupes RawEvents across sources and merges matches into
    one, taking the union of `discovered_via` and `sources`. `enrich.py` then
    adds `audience`/`geographic_origin` (see Event below) to build the final
    output, so those inferred fields live only on Event, not here.
    """

    name: str
    name_local: str | None = None
    category: EventCategory | None = None
    subcategory: str | None = None
    description: str | None = None

    start_date: date | None = None
    end_date: date | None = None
    date_confidence: ConfidenceLevel | None = None

    venue_name: str | None = None
    venue_address: str | None = None
    venue_district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_outdoor: bool | None = None

    organizer: str | None = None
    url: str | None = None
    is_free: bool | None = None
    price_note: str | None = None

    attendance_value: int | None = None
    attendance_low: int | None = None
    attendance_high: int | None = None
    attendance_basis: AttendanceBasis | None = None
    attendance_source_url: str | None = None
    exhibitors: int | None = None
    scale_tier: ScaleTier | None = None

    sources: list[SourceRef] = Field(default_factory=list)
    discovered_via: list[DiscoverySource] = Field(default_factory=list)


# --- Final Event and its nested models --------------------------------------


class EventDates(BaseModel):
    start_date: date
    end_date: date | None = None
    date_confidence: ConfidenceLevel


class EventVenue(BaseModel):
    name: str | None = None
    address: str | None = None
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_outdoor: bool | None = None


class EventTicketing(BaseModel):
    is_free: bool | None = None
    price_note: str | None = None


class EventAttendance(BaseModel):
    value: int | None = None
    low: int | None = None
    high: int | None = None
    basis: AttendanceBasis
    source_url: str | None = None


class EventScale(BaseModel):
    attendance: EventAttendance
    exhibitors: int | None = None
    scale_tier: ScaleTier


class EventAudience(BaseModel):
    """Inferred, never reported. See `confidence` and `rationale`."""

    type: AudienceType
    segments: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
    rationale: str


class GeographicOrigin(BaseModel):
    region: str
    country_codes: list[str] = Field(default_factory=list)
    scope: GeoScope
    share: ConfidenceLevel


class EventGeographicOrigin(BaseModel):
    """Inferred, never reported. See `confidence` and `rationale`."""

    primary: list[GeographicOrigin] = Field(default_factory=list)
    international_share: ConfidenceLevel | None = None
    confidence: ConfidenceLevel
    rationale: str


class EventEvidence(BaseModel):
    sources: list[SourceRef]
    discovered_via: list[DiscoverySource]
    corroborated: bool
    fact_fields: list[str] = Field(default_factory=list)
    inferred_fields: list[str] = Field(default_factory=list)


class EventDataQuality(BaseModel):
    overall_confidence: ConfidenceLevel
    notes: str | None = None


class Event(BaseModel):
    id: str
    name: str
    name_local: str | None = None
    category: EventCategory
    subcategory: str | None = None
    description: str | None = Field(default=None, max_length=300)

    dates: EventDates
    venue: EventVenue
    organizer: str | None = None
    url: str | None = None
    ticketing: EventTicketing

    scale: EventScale
    audience: EventAudience
    geographic_origin: EventGeographicOrigin
    evidence: EventEvidence
    data_quality: EventDataQuality


# --- Top-level output -------------------------------------------------------


class EventQuery(BaseModel):
    city: str
    country_code: str
    month: str  # YYYY-MM


class PipelineInfo(BaseModel):
    models: dict[str, str]
    sources_used: list[DiscoverySource]
    search_queries_executed: int
    api_calls: int
    cache_hits: int
    estimated_cost_usd: float


class Attribution(BaseModel):
    source: str
    url: str
    license_or_terms: str


class EventStats(BaseModel):
    event_count: int
    by_category: dict[str, int]
    by_source: dict[str, int]
    corroborated_count: int
    dropped_by_reason: dict[str, int]


class EventScoutOutput(BaseModel):
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime
    query: EventQuery
    pipeline: PipelineInfo
    attributions: list[Attribution]
    stats: EventStats
    events: list[Event]
