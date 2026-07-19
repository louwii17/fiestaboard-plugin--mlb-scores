"""Fast, favorite-team MLB scores for FiestaBoard."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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

BASE_TRIGGER_PRIORITY = 50
MISSING_GAME_GRACE_SECONDS = 90


@dataclass
class GameLifecycle:
    """Takeover state retained across MLB schedule refreshes."""

    was_live: bool = False
    last_seen_at: datetime | None = None
    delay_until: datetime | None = None
    final_until: datetime | None = None


class MlbScoresPlugin(PluginBase):
    """Display MLB games and trigger a custom page for live favorites."""

    def __init__(self, manifest: dict[str, Any]):
        self._provider: MlbProvider | None = None
        self._trigger_games: list[dict[str, Any]] = []
        self._lifecycles: dict[str, GameLifecycle] = {}
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
            final_seconds = int(config.get("final_display_seconds", 120))
            if not 10 <= final_seconds <= 900:
                errors.append("Final score display time must be between 10 and 900 seconds")
        except (TypeError, ValueError):
            errors.append("Final score display time must be a number")
        try:
            delay_seconds = int(config.get("delay_display_seconds", 300))
            if not 0 <= delay_seconds <= 1800:
                errors.append("Delayed game display time must be between 0 and 1800 seconds")
        except (TypeError, ValueError):
            errors.append("Delayed game display time must be a number")
        try:
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
        self._trigger_games.clear()
        self._lifecycles.clear()

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

        width = int(getattr(self.board, "width", 22) or 22)
        timezone_name = str(self.config.get("timezone", "UTC"))
        indicators = self._indicator_config()
        self._trigger_games = [self._serialize(game, width, timezone_name, indicators) for game in games]
        relevant_games = [game for game in games if self._is_relevant_game(game, now, timezone_name)]
        serialized = [self._serialize(game, width, timezone_name, indicators) for game in relevant_games]
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
        delay_display_seconds = int(self.config.get("delay_display_seconds", 300))
        candidates: dict[int, tuple[tuple[Any, ...], TriggerResult]] = {}
        seen_game_ids: set[str] = set()
        for game in self._trigger_games:
            if not game.get("favorite"):
                continue

            game_id = str(game["game_id"])
            seen_game_ids.add(game_id)
            state = str(game.get("state") or "unknown")
            favorite_rank = int(game.get("favorite_rank") or 0)
            favorite_key = str(game.get("favorite_key") or favorite_rank)
            lifecycle = self._lifecycles.setdefault(game_id, GameLifecycle())
            lifecycle.last_seen_at = now
            duration: int | None = None

            if state == "live":
                if str(game.get("phase") or "") == "FINAL":
                    state = "final"
                else:
                    lifecycle.was_live = True
                    lifecycle.delay_until = None
                    lifecycle.final_until = None
                    duration = live_duration
            if state == "delayed":
                lifecycle.final_until = None
                if lifecycle.was_live and delay_display_seconds > 0:
                    if lifecycle.delay_until is None:
                        lifecycle.delay_until = now + timedelta(seconds=delay_display_seconds)
                    if lifecycle.delay_until > now:
                        duration = min(
                            live_duration,
                            max(1, math.ceil((lifecycle.delay_until - now).total_seconds())),
                        )
                    else:
                        self._lifecycles.pop(game_id, None)
            elif state == "final":
                lifecycle.delay_until = None
                if lifecycle.was_live and lifecycle.final_until is None:
                    lifecycle.final_until = now + timedelta(seconds=final_display_seconds)
                deadline = lifecycle.final_until
                if deadline is not None and deadline > now:
                    duration = max(1, math.ceil((deadline - now).total_seconds()))
                elif deadline is not None:
                    self._lifecycles.pop(game_id, None)
            elif state in {"postponed", "cancelled"}:
                self._lifecycles.pop(game_id, None)

            if duration is None:
                continue

            trigger = TriggerResult(
                triggered=True,
                # One active slot per favorite lets a newly-live doubleheader
                # replace that team's final-hold candidate immediately.
                trigger_id=f"mlb_scores:{favorite_key}",
                # FiestaBoard only arbitrates triggers by integer priority,
                # so encode the user's favorite-team order below NOTABLE.
                priority=max(1, BASE_TRIGGER_PRIORITY - favorite_rank),
                duration_seconds=duration,
                data=game,
            )
            candidate_key = self._trigger_candidate_key(game, state)
            current = candidates.get(favorite_rank)
            if current is None or candidate_key < current[0]:
                candidates[favorite_rank] = (candidate_key, trigger)

        stale_before = now - timedelta(seconds=max(MISSING_GAME_GRACE_SECONDS, live_duration * 2))
        for game_id, lifecycle in list(self._lifecycles.items()):
            if game_id not in seen_game_ids and lifecycle.last_seen_at and lifecycle.last_seen_at < stale_before:
                self._lifecycles.pop(game_id, None)

        return [candidate[1] for _, candidate in sorted(candidates.items())]

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
            favorite_match = self._favorite_match(game)
            favorite_rank = favorite_match[0] if favorite_match is not None else None
            game.details["favorite"] = favorite_rank is not None
            game.details["favorite_rank"] = favorite_rank
            game.details["favorite_key"] = favorite_match[1] if favorite_match is not None else ""
            if not favorites_only or favorite_rank is not None:
                result.append(game)
        return sorted(result, key=lambda game: self._sort_key(game, now))

    def _favorite_match(self, game: Game) -> tuple[int, str] | None:
        """Return the matching team's zero-based rank and normalized config key."""
        raw = self.config.get("favorite_teams", [])
        values = raw if isinstance(raw, list) else str(raw).split(",")
        names = {board_text(game.home.name), board_text(game.away.name)}
        abbreviations = {board_text(game.home.abbreviation), board_text(game.away.abbreviation)}
        for rank, value in enumerate(values):
            if not str(value).strip():
                continue
            token = board_text(str(value))
            if token in abbreviations or token in names:
                return rank, token
            if len(token) > 4 and any(token in name or name in token for name in names):
                return rank, token
        return None

    @staticmethod
    def _is_relevant_game(game: Game, now: datetime, timezone_name: str) -> bool:
        """Keep the local-day slate plus active and recent overnight games."""
        try:
            timezone = ZoneInfo(timezone_name)
        except Exception:
            timezone = ZoneInfo("UTC")
        local_today = now.astimezone(timezone).date()
        local_game_date = game.start_time.astimezone(timezone).date()
        if game.state in {"live", "delayed"}:
            return True
        if local_game_date == local_today:
            return True
        return (
            game.state == "final"
            and local_game_date == local_today - timedelta(days=1)
            and 0 <= (now - game.start_time).total_seconds() <= 12 * 60 * 60
        )

    @staticmethod
    def _trigger_candidate_key(game: dict[str, Any], effective_state: str) -> tuple[Any, ...]:
        """Rank one takeover candidate within a single favorite team."""
        state_rank = {"live": 0, "delayed": 1, "final": 2}.get(effective_state, 3)
        try:
            started_at = datetime.fromisoformat(str(game.get("start_time") or ""))
            recent_rank = -started_at.timestamp()
        except (TypeError, ValueError):
            recent_rank = 0.0
        return state_rank, recent_rank, str(game.get("game_id") or "")

    @staticmethod
    def _sort_key(game: Game, now: datetime) -> tuple[Any, ...]:
        priority = {
            "live": 0,
            "delayed": 1,
            "scheduled": 2,
            "final": 3,
            "postponed": 4,
            "cancelled": 5,
            "unknown": 6,
        }.get(game.state, 6)
        favorite_rank = game.details.get("favorite_rank")
        if favorite_rank is None:
            favorite_rank = 10_000
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
        phase_short = game.phase
        for full_phase, short_phase in (("BOTTOM", "BOT"), ("MIDDLE", "MID")):
            if game.phase.startswith(full_phase):
                phase_short = f"{short_phase}{game.phase[len(full_phase) :]}"
                break
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
            "favorite_rank": game.details.get("favorite_rank"),
            "favorite_key": str(game.details.get("favorite_key") or ""),
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
            "inning_info": "", "favorite": False, "favorite_rank": None,
            "favorite_key": "", "formatted": "", "progress": "",
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
