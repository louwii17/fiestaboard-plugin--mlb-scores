"""OpenLigaDB provider for the FIFA World Cup."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..formatting import team_abbreviation
from ..models import Game, Team, as_int, parse_datetime
from .base import BaseProvider


class OpenLigaDbProvider(BaseProvider):
    name = "openligadb"
    schedule_url = "https://api.openligadb.de/getmatchdata/wm26/2026"
    match_url = "https://api.openligadb.de/getmatchdata/{match_id}"

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._raw_schedule: list[dict[str, Any]] = []
        self._schedule_expires: datetime | None = None

    def clear_cache(self) -> None:
        super().clear_cache()
        self._raw_schedule = []
        self._schedule_expires = None

    def fetch_games(self, now: datetime) -> list[Game]:
        if not self._raw_schedule or not self._schedule_expires or now >= self._schedule_expires:
            payload = self._get_json(self.schedule_url)
            self._raw_schedule = payload if isinstance(payload, list) else []
            self._schedule_expires = now + timedelta(hours=6)

        # During the live window, refresh only the relevant match instead of
        # downloading the complete tournament every minute.
        refreshed: dict[str, dict[str, Any]] = {}
        for raw in self._raw_schedule:
            if raw.get("matchIsFinished"):
                continue
            start = parse_datetime(raw.get("matchDateTimeUTC") or raw.get("matchDateTime"))
            if now - timedelta(hours=4) <= start <= now + timedelta(minutes=30):
                match_id = str(raw.get("matchID", ""))
                if match_id:
                    latest = self._get_json(self.match_url.format(match_id=match_id))
                    if isinstance(latest, dict):
                        refreshed[match_id] = latest

        if refreshed:
            self._raw_schedule = [refreshed.get(str(raw.get("matchID", "")), raw) for raw in self._raw_schedule]

        games: list[Game] = []
        for raw in self._raw_schedule:
            parsed = self._parse_game(raw, now)
            if parsed:
                games.append(parsed)
        return games

    def _parse_game(self, raw: dict[str, Any], now: datetime) -> Game | None:
        match_id = raw.get("matchID")
        team1 = raw.get("team1") or {}
        team2 = raw.get("team2") or {}
        if not match_id or not team1 or not team2:
            return None

        start = parse_datetime(raw.get("matchDateTimeUTC") or raw.get("matchDateTime"))
        if raw.get("matchIsFinished"):
            state = "final"
        elif start <= now <= start + timedelta(hours=4):
            state = "live"
        else:
            state = "scheduled"

        score1, score2 = self._score(raw)
        group = raw.get("group") or {}
        round_name = str(group.get("groupName") or "World Cup")
        status = "Final" if state == "final" else "Live" if state == "live" else "Scheduled"
        last_updated = raw.get("lastUpdateDateTime")

        return Game(
            id=str(match_id),
            sport="FIFA",
            league="FIFA World Cup",
            source=self.name,
            start_time=start,
            state=state,
            status=status,
            phase="FINAL" if state == "final" else "LIVE" if state == "live" else round_name,
            clock="",
            home=self._team(team1, score1),
            away=self._team(team2, score2),
            details={"round": round_name},
            last_updated=parse_datetime(last_updated) if last_updated else None,
        )

    @staticmethod
    def _score(raw: dict[str, Any]) -> tuple[int | None, int | None]:
        results = [result for result in raw.get("matchResults", []) if isinstance(result, dict)]
        if results:
            result = max(results, key=lambda item: as_int(item.get("resultOrder"), 0) or 0)
            return as_int(result.get("pointsTeam1")), as_int(result.get("pointsTeam2"))
        goals = [goal for goal in raw.get("goals", []) if isinstance(goal, dict)]
        if goals:
            goal = goals[-1]
            return as_int(goal.get("scoreTeam1")), as_int(goal.get("scoreTeam2"))
        return None, None

    @staticmethod
    def _team(raw: dict[str, Any], score: int | None) -> Team:
        name = str(raw.get("teamName") or raw.get("shortName") or "Unknown")
        abbreviation = str(raw.get("shortName") or team_abbreviation(name, max_length=4))
        return Team(
            id=str(raw.get("teamId", "")),
            name=name,
            abbreviation=abbreviation,
            score=score,
        )

