"""Live MLB, NHL, and FIFA World Cup scores for FiestaBoard."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timezone
from typing import Any

from src.plugins.base import PluginBase, PluginResult, TriggerResult

from .formatting import (
    board_text,
    format_progress,
    format_score,
    game_datetime,
    result_colors,
    team_abbreviation,
    team_color,
)
from .models import Game
from .providers import ApiSportsFifaProvider, MlbProvider, NhlProvider, OpenLigaDbProvider, ProviderError

logger = logging.getLogger(__name__)

VALID_SPORTS = {"FIFA", "MLB", "NHL"}


class LiveSportsPlugin(PluginBase):
    """Combine free official/community sports feeds behind one schema."""

    def __init__(self, manifest: dict[str, Any]):
        super().__init__(manifest)
        self._providers: dict[str, Any] = {}

    @property
    def plugin_id(self) -> str:
        return "live_sports"

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        sports = config.get("sports", ["MLB"])
        if not sports:
            errors.append("At least one sport must be selected")
        invalid = [sport for sport in sports if sport not in VALID_SPORTS]
        if invalid:
            errors.append(f"Invalid sports: {', '.join(invalid)}")
        provider = config.get("fifa_provider", "openligadb")
        if provider not in {"openligadb", "api_sports"}:
            errors.append("FIFA provider must be openligadb or api_sports")
        if provider == "api_sports" and not str(config.get("api_sports_key", "")).strip():
            errors.append("API-Sports key is required when API-Sports is selected")
        try:
            maximum = int(config.get("max_games_per_sport", 3))
            if not 1 <= maximum <= 10:
                errors.append("Max games per sport must be between 1 and 10")
        except (TypeError, ValueError):
            errors.append("Max games per sport must be a number")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(str(config.get("timezone", "UTC")))
        except Exception:
            errors.append("Timezone must be a valid IANA name, such as America/Toronto")
        return errors

    def on_config_change(self, old_config: dict[str, Any], new_config: dict[str, Any]) -> None:
        for provider in self._providers.values():
            provider.clear_cache()
        self._providers = {}

    def fetch_data(self) -> PluginResult:
        sports = self.config.get("sports", ["MLB"])
        if not sports:
            return PluginResult(available=False, error="No sports selected")

        now = datetime.now(UTC)
        per_sport: dict[str, list[Game]] = {sport.lower(): [] for sport in VALID_SPORTS}
        failures: list[str] = []
        for sport in sports:
            try:
                per_sport[sport.lower()] = self._games_for(sport, now)
            except ProviderError as exc:
                failures.append(str(exc))
                logger.warning("Unable to fetch %s: %s", sport, exc)

        games = [game for sport in sports for game in per_sport[sport.lower()]]
        games = self._filter_and_sort(games, now)
        maximum = int(self.config.get("max_games_per_sport", 3))
        selected: list[Game] = []
        for sport in sports:
            selected.extend([game for game in games if game.sport == sport][:maximum])
        selected.sort(key=lambda game: self._sort_key(game, now))

        if not selected and failures and len(failures) == len(sports):
            return PluginResult(available=False, error="; ".join(failures))

        width = int(getattr(self.board, "width", 22) or 22)
        timezone_name = str(self.config.get("timezone", "UTC"))
        serialized = [self._serialize(game, width, timezone_name) for game in selected]
        by_sport = {
            sport.lower(): [item for item in serialized if item["sport"] == sport]
            for sport in VALID_SPORTS
        }
        primary = serialized[0] if serialized else self._empty_game()
        data = {
            **primary,
            "games": serialized,
            **by_sport,
            "game_count": len(serialized),
            "sport_count": len(sports),
            "errors": failures,
            "last_updated": now.isoformat(),
        }
        return PluginResult(
            available=True,
            data=data,
            formatted_lines=self._formatted_lines(serialized, width),
        )

    def get_formatted_display(self) -> list[str] | None:
        result = self.fetch_data()
        return result.formatted_lines if result.available else None

    def check_triggers(self) -> list[TriggerResult]:
        """Keep one native FiestaBoard override active per live favorite game."""
        result = self.get_data()
        if not result.available or not result.data:
            return []

        refresh = int(self.config.get("refresh_seconds", 10))
        duration = max(45, min(refresh * 3, 180))
        triggers: list[TriggerResult] = []
        for game in result.data.get("games", []):
            if not game.get("favorite") or game.get("state") != "live":
                continue
            triggers.append(
                TriggerResult(
                    triggered=True,
                    trigger_id=f"live_sports:mlb:{game['game_id']}",
                    priority=50,
                    duration_seconds=duration,
                    data=game,
                    formatted_lines=[
                        self._inning_line(game),
                        self._team_line(game, "away"),
                        self._team_line(game, "home"),
                    ],
                )
            )
        return triggers

    def _games_for(self, sport: str, now: datetime) -> list[Game]:
        if sport != "FIFA":
            return self._provider_for(sport).get_games(now)
        preferred = str(self.config.get("fifa_provider", "openligadb"))
        try:
            return self._provider_for(f"FIFA:{preferred}").get_games(now)
        except ProviderError:
            key = str(self.config.get("api_sports_key", "")).strip()
            if preferred == "openligadb" and key:
                logger.info("OpenLigaDB unavailable; trying API-Sports fallback")
                return self._provider_for("FIFA:api_sports").get_games(now)
            raise

    def _provider_for(self, key: str) -> Any:
        if key in self._providers:
            return self._providers[key]
        timezone_name = str(self.config.get("timezone", "UTC"))
        if key == "MLB":
            provider = MlbProvider(
                timezone_name=timezone_name,
                live_refresh_seconds=int(self.config.get("refresh_seconds", 10)),
            )
        elif key == "NHL":
            provider = NhlProvider()
        elif key == "FIFA:openligadb":
            provider = OpenLigaDbProvider()
        elif key == "FIFA:api_sports":
            provider = ApiSportsFifaProvider(
                api_key=str(self.config.get("api_sports_key", "")),
                timezone_name=timezone_name,
            )
        else:
            raise ProviderError(f"Unknown sport/provider: {key}")
        self._providers[key] = provider
        return provider

    def _filter_and_sort(self, games: list[Game], now: datetime) -> list[Game]:
        favorites_only = bool(self.config.get("favorites_only", False))
        result: list[Game] = []
        for game in games:
            favorite = self._is_favorite(game)
            game.details["favorite"] = favorite
            if not favorites_only or favorite:
                result.append(game)
        return sorted(result, key=lambda game: self._sort_key(game, now))

    def _is_favorite(self, game: Game) -> bool:
        raw = self.config.get(f"{game.sport.lower()}_teams", "")
        values = raw if isinstance(raw, list) else str(raw).split(",")
        wanted = [board_text(str(value)) for value in values if str(value).strip()]
        if not wanted:
            return False
        names = {
            board_text(game.home.name),
            board_text(game.away.name),
        }
        abbreviations = {
            board_text(game.home.abbreviation),
            board_text(game.away.abbreviation),
        }
        for token in wanted:
            if token in abbreviations or token in names:
                return True
            if len(token) > 4 and any(token in name or name in token for name in names):
                return True
        return False

    @staticmethod
    def _sort_key(game: Game, now: datetime) -> tuple[Any, ...]:
        priority = {
            "live": 0,
            "intermission": 0,
            "scheduled": 1,
            "delayed": 2,
            "final": 3,
            "postponed": 4,
            "cancelled": 5,
            "unknown": 6,
        }.get(game.state, 6)
        favorite_rank = 0 if game.details.get("favorite") else 1
        distance = abs((game.start_time - now).total_seconds())
        return priority, favorite_rank, distance, game.start_time, game.id

    @staticmethod
    def _serialize(game: Game, width: int, timezone_name: str) -> dict[str, Any]:
        date, local_time = game_datetime(game, timezone_name)
        away_result_color, home_result_color = result_colors(game)
        away_short = team_abbreviation(game.away.name, game.away.abbreviation)
        home_short = team_abbreviation(game.home.name, game.home.abbreviation)
        away_nickname = board_text(game.away.short_name or game.away.name)
        home_nickname = board_text(game.home.short_name or game.home.name)
        away_color = team_color(game.sport, away_short)
        home_color = team_color(game.sport, home_short)
        inning_half = board_text(str(game.details.get("inning_half") or ""))
        inning_number = game.details.get("inning")
        inning_ordinal = board_text(str(game.details.get("inning_ordinal") or ""))
        outs = game.details.get("outs")
        outs_text = "" if outs is None else f"{outs} {'OUT' if outs == 1 else 'OUTS'}"
        inning_info = " ".join(part for part in (inning_half, inning_ordinal, outs_text) if part)
        return {
            "game_id": game.id,
            "sport": game.sport,
            "league": game.league,
            "source": game.source,
            "state": game.state,
            "status": game.status,
            "phase": game.phase,
            "clock": game.clock,
            "date": date,
            "time": local_time,
            "start_time": game.start_time.isoformat(),
            "team1": away_short,
            "team2": home_short,
            "team1_full": game.away.name,
            "team2_full": game.home.name,
            "score1": game.away.score,
            "score2": game.home.score,
            "team1_color": away_color,
            "team2_color": home_color,
            "team1_result_color": away_result_color,
            "team2_result_color": home_result_color,
            "away_short": away_short,
            "away_name": game.away.name,
            "away_nickname": away_nickname,
            "away_score": game.away.score,
            "away_color": away_color,
            "away_result_color": away_result_color,
            "home_short": home_short,
            "home_name": game.home.name,
            "home_nickname": home_nickname,
            "home_score": game.home.score,
            "home_color": home_color,
            "home_result_color": home_result_color,
            "inning_half": inning_half,
            "inning_number": inning_number,
            "inning_ordinal": inning_ordinal,
            "outs": outs,
            "outs_text": outs_text,
            "inning_info": board_text(inning_info)[:width],
            "favorite": bool(game.details.get("favorite")),
            "formatted": format_score(game, width),
            "progress": format_progress(game, width, timezone_name),
        }

    @staticmethod
    def _empty_game() -> dict[str, Any]:
        return {
            "sport": "", "team1": "", "team2": "", "team1_full": "", "team2_full": "",
            "score1": None, "score2": None, "status": "", "state": "", "formatted": "",
            "progress": "", "date": "", "time": "", "source": "", "game_id": "",
            "away_short": "", "away_name": "", "away_nickname": "", "away_score": None, "away_color": "",
            "away_result_color": "", "home_short": "", "home_name": "", "home_nickname": "", "home_score": None,
            "home_color": "", "home_result_color": "", "inning_half": "", "inning_number": None,
            "inning_ordinal": "", "outs": None, "outs_text": "", "inning_info": "",
        }

    @staticmethod
    def _formatted_lines(games: list[dict[str, Any]], width: int) -> list[str]:
        height = 6 if width >= 20 else 3
        if not games:
            return ["LIVE SPORTS", "NO GAMES TODAY"][:height]
        lines = ["LIVE SPORTS"]
        for game in games:
            lines.append(str(game["formatted"]))
            if len(lines) < height:
                lines.append(str(game["progress"]))
            if len(lines) >= height:
                break
        return lines[:height]

    @staticmethod
    def _team_line(game: dict[str, Any], side: str) -> str:
        """Return a compact Note-safe fallback; custom pages use raw fields."""
        color = str(game.get(f"{side}_color") or "")
        short = str(game.get(f"{side}_short") or "")
        score = game.get(f"{side}_score")
        score_text = "?" if score is None else str(score)
        return f"{color} {short[:10].ljust(10)}{score_text.rjust(3)}"

    @staticmethod
    def _inning_line(game: dict[str, Any]) -> str:
        """Return a 15-cell inning/outs line without ordinal suffixes."""
        half = str(game.get("inning_half") or "")
        number = game.get("inning_number")
        outs = game.get("outs")
        inning = f"{half} {'' if number is None else number}".strip()
        if outs is None:
            outs_label = "? OUTS"
        else:
            outs_label = f"{outs} {'OUT' if outs == 1 else 'OUTS'}"
        return f"{inning[:9].ljust(9)}{outs_label.rjust(6)}"[:15]


Plugin = LiveSportsPlugin

__all__ = ["LiveSportsPlugin", "Plugin"]
