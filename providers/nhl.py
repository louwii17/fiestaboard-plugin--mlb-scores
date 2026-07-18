"""NHL GameCenter API provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..formatting import team_abbreviation
from ..models import Game, Team, as_int, parse_datetime
from .base import BaseProvider


class NhlProvider(BaseProvider):
    name = "nhl"
    url = "https://api-web.nhle.com/v1/score/now"

    def fetch_games(self, now: datetime) -> list[Game]:
        payload = self._get_json(self.url)
        raw_games = list(payload.get("games", []))
        for day in payload.get("gameWeek", []):
            raw_games.extend(day.get("games", []))

        seen: set[str] = set()
        games: list[Game] = []
        for raw in raw_games:
            game_id = str(raw.get("id", ""))
            if not game_id or game_id in seen:
                continue
            seen.add(game_id)
            parsed = self._parse_game(raw)
            if parsed:
                games.append(parsed)
        return games

    def _parse_game(self, raw: dict[str, Any]) -> Game | None:
        game_id = raw.get("id")
        if not game_id or not raw.get("homeTeam") or not raw.get("awayTeam"):
            return None

        game_state = str(raw.get("gameState", "FUT")).upper()
        state_map = {
            "FUT": "scheduled",
            "PRE": "scheduled",
            "LIVE": "live",
            "CRIT": "live",
            "OFF": "final",
            "FINAL": "final",
        }
        state = state_map.get(game_state, "unknown")
        clock_data = raw.get("clock") or {}
        if state == "live" and clock_data.get("inIntermission"):
            state = "intermission"

        descriptor = raw.get("periodDescriptor") or {}
        period = as_int(descriptor.get("number"))
        period_type = str(descriptor.get("periodType", "REG")).upper()
        if state == "final":
            outcome = raw.get("gameOutcome") or {}
            last_type = str(outcome.get("lastPeriodType", period_type)).upper()
            phase = "FINAL" if last_type == "REG" else f"FINAL/{last_type}"
        elif period_type == "SO":
            phase = "SHOOTOUT"
        elif period_type == "OT":
            phase = "OT"
        elif period:
            phase = f"{period}{'ST' if period == 1 else 'ND' if period == 2 else 'RD'}"
        else:
            phase = ""

        return Game(
            id=str(game_id),
            sport="NHL",
            league="NHL",
            source=self.name,
            start_time=parse_datetime(raw.get("startTimeUTC")),
            state=state,
            status=game_state,
            phase=phase,
            clock=str(clock_data.get("timeRemaining") or ""),
            home=self._team(raw["homeTeam"]),
            away=self._team(raw["awayTeam"]),
            details={
                "period": period,
                "period_type": period_type,
                "in_intermission": bool(clock_data.get("inIntermission")),
            },
        )

    @staticmethod
    def _team(raw: dict[str, Any]) -> Team:
        place = raw.get("placeName") or {}
        common = raw.get("commonName") or {}
        place_name = place.get("default", "") if isinstance(place, dict) else str(place)
        common_name = common.get("default", "") if isinstance(common, dict) else str(common)
        name = " ".join(part for part in (place_name, common_name) if part).strip()
        abbreviation = str(raw.get("abbrev") or team_abbreviation(name))
        return Team(
            id=str(raw.get("id", "")),
            name=name or abbreviation,
            abbreviation=abbreviation,
            score=as_int(raw.get("score")),
        )

