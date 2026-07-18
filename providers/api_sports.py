"""Optional API-Sports provider for FIFA World Cup scores."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..formatting import team_abbreviation
from ..models import Game, Team, as_int, parse_datetime
from .base import BaseProvider, ProviderError


class ApiSportsFifaProvider(BaseProvider):
    name = "api_sports"
    url = "https://v3.football.api-sports.io/fixtures"

    def __init__(self, api_key: str, timezone_name: str = "UTC", **kwargs: Any):
        super().__init__(**kwargs)
        self.api_key = api_key.strip()
        self.timezone_name = timezone_name

    def fetch_games(self, now: datetime) -> list[Game]:
        if not self.api_key:
            raise ProviderError("API-Sports key is required")
        try:
            local_date = now.astimezone(ZoneInfo(self.timezone_name)).date()
        except Exception:
            local_date = now.date()
        payload = self._get_json(
            self.url,
            params={"league": 1, "season": 2026, "date": local_date.isoformat()},
            headers={"x-apisports-key": self.api_key},
        )
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            raise ProviderError(str(errors))
        games: list[Game] = []
        for raw in payload.get("response", []):
            parsed = self._parse_game(raw)
            if parsed:
                games.append(parsed)
        return games

    def _parse_game(self, raw: dict[str, Any]) -> Game | None:
        fixture = raw.get("fixture") or {}
        teams = raw.get("teams") or {}
        if not fixture.get("id") or not teams.get("home") or not teams.get("away"):
            return None
        status = fixture.get("status") or {}
        short = str(status.get("short", "NS")).upper()
        if short in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}:
            state = "intermission" if short in {"HT", "BT"} else "live"
        elif short in {"FT", "AET", "PEN"}:
            state = "final"
        elif short in {"PST", "SUSP", "INT"}:
            state = "postponed" if short == "PST" else "delayed"
        elif short in {"CANC", "ABD", "AWD", "WO"}:
            state = "cancelled"
        else:
            state = "scheduled"
        elapsed = as_int(status.get("elapsed"))
        phase = "FINAL" if state == "final" else short if state != "scheduled" else str((raw.get("league") or {}).get("round", ""))
        clock = f"{elapsed}'" if elapsed is not None and state == "live" else ""
        goals = raw.get("goals") or {}
        return Game(
            id=str(fixture["id"]),
            sport="FIFA",
            league="FIFA World Cup",
            source=self.name,
            start_time=parse_datetime(fixture.get("date")),
            state=state,
            status=str(status.get("long") or short),
            phase=phase,
            clock=clock,
            home=self._team(teams["home"], goals.get("home")),
            away=self._team(teams["away"], goals.get("away")),
            details={"elapsed": elapsed},
        )

    @staticmethod
    def _team(raw: dict[str, Any], score: Any) -> Team:
        name = str(raw.get("name") or "Unknown")
        return Team(
            id=str(raw.get("id", "")),
            name=name,
            abbreviation=team_abbreviation(name, max_length=4),
            score=as_int(score),
        )
