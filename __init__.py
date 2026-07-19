"""Fast, favorite-team MLB scores for FiestaBoard."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from src.plugins.base import PluginBase, PluginResult, TriggerResult

from .formatting import (
    board_text,
    format_progress,
    format_score,
    game_datetime,
    indicator_cell,
    outs_indicator,
    result_colors,
    team_abbreviation,
    team_color,
)
from .models import Game
from .providers import MlbProvider, ProviderError

logger = logging.getLogger(__name__)


class MlbScoresPlugin(PluginBase):
    """Display MLB games and trigger a custom page for live favorites."""

    def __init__(self, manifest: dict[str, Any]):
        self._provider: MlbProvider | None = None
        self._takeover_game_ids: set[str] = set()
        self._final_until: dict[str, datetime] = {}
        super().__init__(manifest)

    @property
    def plugin_id(self) -> str:
        return "mlb_scores"

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        favorites = config.get("favorite_teams", [])
        if favorites and not isinstance(favorites, (list, str)):
            errors.append("Favorite teams must be a list of MLB abbreviations")
        try:
            maximum = int(config.get("max_games", 3))
            if not 1 <= maximum <= 10:
                errors.append("Max games must be between 1 and 10")
        except (TypeError, ValueError):
            errors.append("Max games must be a number")
        try:
            final_seconds = int(config.get("final_display_seconds", 120))
            if not 10 <= final_seconds <= 900:
                errors.append("Final score display time must be between 10 and 900 seconds")
        except (TypeError, ValueError):
            errors.append("Final score display time must be a number")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(str(config.get("timezone", "UTC")))
        except Exception:
            errors.append("Timezone must be a valid IANA name, such as America/Toronto")
        indicator_defaults = {
            "outs_indicator_on": "{69}",
            "outs_indicator_off": ".",
            "base_indicator_on": "{65}",
            "base_indicator_off": ".",
        }
        for key, default in indicator_defaults.items():
            if key in config:
                raw_indicator = str(config[key])
                normalized_indicator = indicator_cell(config[key], default)
                if normalized_indicator != raw_indicator and raw_indicator != "{0}":
                    errors.append(
                        f"{key} must be one character, {{0}} for blank, "
                        "or a color code from {63} to {71}"
                    )
        return errors

    def on_config_change(self, old_config: dict[str, Any], new_config: dict[str, Any]) -> None:
        if self._provider is not None:
            self._provider.clear_cache()
        self._provider = None
        self._takeover_game_ids.clear()
        self._final_until.clear()

    def _now(self) -> datetime:
        """Return the current UTC time; isolated for deterministic lifecycle tests."""
        return datetime.now(UTC)

    def fetch_data(self) -> PluginResult:
        now = self._now()
        try:
            games = self._get_provider().get_games(now)
        except ProviderError as exc:
            logger.warning("Unable to fetch MLB games: %s", exc)
            return PluginResult(available=False, error=str(exc))

        games = self._filter_and_sort(games, now)
        maximum = int(self.config.get("max_games", 3))
        selected = games[:maximum]

        width = int(getattr(self.board, "width", 22) or 22)
        timezone_name = str(self.config.get("timezone", "UTC"))
        indicators = self._indicator_config()
        serialized = [self._serialize(game, width, timezone_name, indicators) for game in selected]
        primary = serialized[0] if serialized else self._empty_game()
        data = {
            **primary,
            "games": serialized,
            "game_count": len(serialized),
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
        """Keep an override active for live favorites and briefly after final."""
        result = self.get_data()
        if not result.available or not result.data:
            return []

        now = self._now()
        refresh = int(self.config.get("refresh_seconds", 10))
        live_duration = max(45, min(refresh * 3, 180))
        final_display_seconds = int(self.config.get("final_display_seconds", 120))
        triggers: list[TriggerResult] = []
        for game in result.data.get("games", []):
            if not game.get("favorite"):
                continue

            game_id = str(game["game_id"])
            state = str(game.get("state") or "unknown")
            duration: int | None = None

            if state == "live":
                self._takeover_game_ids.add(game_id)
                self._final_until.pop(game_id, None)
                duration = live_duration
            elif state == "final":
                if game_id in self._takeover_game_ids and game_id not in self._final_until:
                    self._final_until[game_id] = now + timedelta(seconds=final_display_seconds)
                deadline = self._final_until.get(game_id)
                if deadline is not None and deadline > now:
                    duration = max(1, math.ceil((deadline - now).total_seconds()))
                elif deadline is not None:
                    self._final_until.pop(game_id, None)
                    self._takeover_game_ids.discard(game_id)
            elif state in {"postponed", "cancelled"}:
                self._final_until.pop(game_id, None)
                self._takeover_game_ids.discard(game_id)

            if duration is None:
                continue

            triggers.append(
                TriggerResult(
                    triggered=True,
                    trigger_id=f"mlb_scores:{game_id}",
                    priority=50,
                    duration_seconds=duration,
                    data=game,
                )
            )
        return triggers

    def _get_provider(self) -> MlbProvider:
        if self._provider is None:
            self._provider = MlbProvider(
                timezone_name=str(self.config.get("timezone", "UTC")),
                live_refresh_seconds=int(self.config.get("refresh_seconds", 10)),
            )
        return self._provider

    def _indicator_config(self) -> dict[str, str]:
        defaults = {
            "outs_indicator_on": "{69}",
            "outs_indicator_off": ".",
            "base_indicator_on": "{65}",
            "base_indicator_off": ".",
        }
        return {
            key: indicator_cell(self.config.get(key, default), default)
            for key, default in defaults.items()
        }

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
        raw = self.config.get("favorite_teams", [])
        values = raw if isinstance(raw, list) else str(raw).split(",")
        wanted = {board_text(str(value)) for value in values if str(value).strip()}
        if not wanted:
            return False
        names = {board_text(game.home.name), board_text(game.away.name)}
        abbreviations = {board_text(game.home.abbreviation), board_text(game.away.abbreviation)}
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
    def _serialize(
        game: Game,
        width: int,
        timezone_name: str,
        indicators: dict[str, str],
    ) -> dict[str, Any]:
        date, local_time = game_datetime(game, timezone_name)
        away_result_color, home_result_color = result_colors(game)
        away_short = team_abbreviation(game.away.name, game.away.abbreviation)
        home_short = team_abbreviation(game.home.name, game.home.abbreviation)
        away_nickname = board_text(game.away.short_name or game.away.name)
        home_nickname = board_text(game.home.short_name or game.home.name)
        away_color = team_color(away_short)
        home_color = team_color(home_short)
        inning_half = board_text(str(game.details.get("inning_half") or ""))
        inning_half_short = {
            "BOTTOM": "BOT",
            "MIDDLE": "MID",
        }.get(inning_half, inning_half)
        inning_number = game.details.get("inning")
        inning_ordinal = board_text(str(game.details.get("inning_ordinal") or ""))
        outs = game.details.get("outs")
        outs_text = "" if outs is None else f"{outs} {'OUT' if outs == 1 else 'OUTS'}"
        rendered_outs_indicator = outs_indicator(
            outs,
            indicators["outs_indicator_on"],
            indicators["outs_indicator_off"],
        )
        first_base_occupied = bool(game.details.get("first_base_occupied"))
        second_base_occupied = bool(game.details.get("second_base_occupied"))
        third_base_occupied = bool(game.details.get("third_base_occupied"))
        phase_short = (
            f"BOT{game.phase[len('BOTTOM') :]}"
            if game.phase.startswith("BOTTOM")
            else game.phase
        )
        inning_info = (
            "FINAL"
            if game.state == "final" or game.phase == "FINAL"
            else " ".join(part for part in (inning_half, str(inning_number or ""), outs_text) if part)
        )
        return {
            "game_id": game.id,
            "state": game.state,
            "status": game.status,
            "phase": game.phase,
            "phase_short": phase_short,
            "date": date,
            "time": local_time,
            "start_time": game.start_time.isoformat(),
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
            "inning_half_short": inning_half_short,
            "inning_number": inning_number,
            "inning_ordinal": inning_ordinal,
            "outs": outs,
            "outs_text": outs_text,
            "outs_indicator": rendered_outs_indicator,
            "first_base_occupied": first_base_occupied,
            "second_base_occupied": second_base_occupied,
            "third_base_occupied": third_base_occupied,
            "first_base_indicator": indicators["base_indicator_on"] if first_base_occupied else indicators["base_indicator_off"],
            "second_base_indicator": indicators["base_indicator_on"] if second_base_occupied else indicators["base_indicator_off"],
            "third_base_indicator": indicators["base_indicator_on"] if third_base_occupied else indicators["base_indicator_off"],
            "inning_info": board_text(inning_info)[:width],
            "favorite": bool(game.details.get("favorite")),
            "formatted": format_score(game, width),
            "progress": format_progress(game, width, timezone_name),
        }

    @staticmethod
    def _empty_game() -> dict[str, Any]:
        return {
            "game_id": "", "state": "", "status": "", "phase": "", "phase_short": "",
            "date": "", "time": "",
            "away_short": "", "away_name": "", "away_nickname": "", "away_score": None,
            "away_color": "", "away_result_color": "", "home_short": "", "home_name": "",
            "home_nickname": "", "home_score": None, "home_color": "", "home_result_color": "",
            "inning_half": "", "inning_half_short": "", "inning_number": None,
            "inning_ordinal": "", "outs": None,
            "outs_text": "", "outs_indicator": "",
            "first_base_occupied": False, "second_base_occupied": False,
            "third_base_occupied": False, "first_base_indicator": "",
            "second_base_indicator": "", "third_base_indicator": "",
            "inning_info": "", "formatted": "", "progress": "",
        }

    @staticmethod
    def _formatted_lines(games: list[dict[str, Any]], width: int) -> list[str]:
        height = 6 if width >= 20 else 3
        if not games:
            return ["MLB SCORES", "NO GAMES TODAY"][:height]
        lines = ["MLB SCORES"]
        for game in games:
            lines.append(str(game["formatted"]))
            if len(lines) < height:
                lines.append(str(game["progress"]))
            if len(lines) >= height:
                break
        return lines[:height]

Plugin = MlbScoresPlugin

__all__ = ["MlbScoresPlugin", "Plugin"]
