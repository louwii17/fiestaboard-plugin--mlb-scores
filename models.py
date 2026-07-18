"""Normalized MLB game models used by the MLB Scores plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

VALID_STATES = {
    "scheduled",
    "live",
    "final",
    "postponed",
    "cancelled",
    "delayed",
    "unknown",
}


def parse_datetime(value: str | None) -> datetime:
    """Parse an ISO timestamp and always return a timezone-aware datetime."""
    if not value:
        return datetime.now(UTC)
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def as_int(value: Any, default: int | None = None) -> int | None:
    """Convert an API value to an integer without raising."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Team:
    """A team in a normalized game response."""

    id: str
    name: str
    abbreviation: str
    score: int | None = None
    short_name: str = ""


@dataclass
class Game:
    """An MLB game normalized for FiestaBoard rendering."""

    id: str
    sport: str
    league: str
    source: str
    start_time: datetime
    state: str
    status: str
    home: Team
    away: Team
    phase: str = ""
    clock: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    last_updated: datetime | None = None

    def __post_init__(self) -> None:
        if self.state not in VALID_STATES:
            self.state = "unknown"
        if self.start_time.tzinfo is None:
            self.start_time = self.start_time.replace(tzinfo=UTC)

    @property
    def is_live(self) -> bool:
        return self.state == "live"

    @property
    def is_final(self) -> bool:
        return self.state == "final"

    @property
    def has_scores(self) -> bool:
        return self.home.score is not None or self.away.score is not None
