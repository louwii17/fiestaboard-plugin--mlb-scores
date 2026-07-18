"""MLB Stats API provider."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..formatting import team_abbreviation
from ..models import Game, Team, as_int, parse_datetime
from .base import BaseProvider


class MlbProvider(BaseProvider):
    name = "mlb"
    url = "https://statsapi.mlb.com/api/v1/schedule"

    def __init__(self, timezone_name: str = "UTC", **kwargs: Any):
        super().__init__(**kwargs)
        self.timezone_name = timezone_name

    def fetch_games(self, now: datetime) -> list[Game]:
        try:
            local_date = now.astimezone(ZoneInfo(self.timezone_name)).date()
        except Exception:
            local_date = now.date()
        # A three-day window keeps west-coast and extra-inning games visible
        # after local midnight and also discovers tomorrow's early games.
        payload = self._get_json(
            self.url,
            params={
                "sportId": 1,
                "startDate": (local_date - timedelta(days=1)).isoformat(),
                "endDate": (local_date + timedelta(days=1)).isoformat(),
                "hydrate": "linescore,team",
            },
        )
        games: list[Game] = []
        for date_block in payload.get("dates", []):
            for raw in date_block.get("games", []):
                parsed = self._parse_game(raw)
                if parsed:
                    games.append(parsed)
        return games

    def _parse_game(self, raw: dict[str, Any]) -> Game | None:
        game_id = raw.get("gamePk")
        teams = raw.get("teams", {})
        if not game_id or not teams.get("home") or not teams.get("away"):
            return None

        status = raw.get("status", {})
        abstract = str(status.get("abstractGameState", "")).lower()
        detailed = str(status.get("detailedState", "Unknown"))
        detail_lower = detailed.lower()
        if "postpon" in detail_lower:
            state = "postponed"
        elif "cancel" in detail_lower:
            state = "cancelled"
        elif "delay" in detail_lower or "suspend" in detail_lower:
            state = "delayed"
        elif abstract == "live" or detail_lower in {"in progress", "manager challenge"}:
            state = "live"
        elif abstract == "final":
            state = "final"
        elif abstract == "preview":
            state = "scheduled"
        else:
            state = "unknown"

        linescore = raw.get("linescore") or {}
        inning_state = str(linescore.get("inningState", ""))
        inning_ordinal = str(linescore.get("currentInningOrdinal", ""))
        outs = as_int(linescore.get("outs"))
        offense = linescore.get("offense") or {}
        show_bases = state in {"live", "delayed"} and outs != 3
        phase = " ".join(part for part in (inning_state, inning_ordinal) if part).upper()
        if state == "final":
            phase = "FINAL"

        home = self._team(teams["home"])
        away = self._team(teams["away"])
        return Game(
            id=str(game_id),
            sport="MLB",
            league="MLB",
            source=self.name,
            start_time=parse_datetime(raw.get("gameDate")),
            state=state,
            status=detailed,
            phase=phase,
            clock="",
            home=home,
            away=away,
            details={
                "inning": as_int(linescore.get("currentInning")),
                "inning_half": inning_state,
                "inning_ordinal": inning_ordinal,
                "outs": outs,
                "first_base_occupied": show_bases and bool(offense.get("first")),
                "second_base_occupied": show_bases and bool(offense.get("second")),
                "third_base_occupied": show_bases and bool(offense.get("third")),
            },
        )

    @staticmethod
    def _team(raw: dict[str, Any]) -> Team:
        team = raw.get("team") or {}
        name = str(team.get("name") or team.get("teamName") or "Unknown")
        short_name = str(team.get("teamName") or team.get("clubName") or name)
        abbreviation = str(team.get("abbreviation") or team_abbreviation(name))
        return Team(
            id=str(team.get("id", "")),
            name=name,
            abbreviation=abbreviation,
            score=as_int(raw.get("score")),
            short_name=short_name,
        )
