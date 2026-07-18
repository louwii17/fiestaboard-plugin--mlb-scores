"""MLB provider HTTP handling and adaptive caching."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from ..models import Game

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Raised when a provider cannot return usable data."""


class BaseProvider(ABC):
    """Base provider with adaptive, in-memory response caching."""

    name = "base"

    def __init__(
        self,
        session: Any | None = None,
        timeout: int = 12,
        live_refresh_seconds: int = 60,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.live_refresh_seconds = max(10, int(live_refresh_seconds))
        self._games: list[Game] = []
        self._next_fetch_at: datetime | None = None
        self.last_error = ""

    def get_games(self, now: datetime | None = None) -> list[Game]:
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if self._next_fetch_at and now < self._next_fetch_at:
            return list(self._games)

        try:
            games = self.fetch_games(now)
            self._games = games
            self.last_error = ""
            self._next_fetch_at = now + timedelta(seconds=self._ttl_for(games, now))
        except Exception as exc:
            self.last_error = str(exc)
            self._next_fetch_at = now + timedelta(minutes=5)
            if not self._games:
                raise ProviderError(f"{self.name}: {exc}") from exc
            logger.warning("%s provider failed; serving cached games: %s", self.name, exc)
        return list(self._games)

    @abstractmethod
    def fetch_games(self, now: datetime) -> list[Game]:
        """Fetch and normalize games from the upstream provider."""

    def clear_cache(self) -> None:
        self._games = []
        self._next_fetch_at = None
        self.last_error = ""

    def _ttl_for(self, games: list[Game], now: datetime) -> int:
        if any(game.is_live for game in games):
            return self.live_refresh_seconds
        future = [game.start_time for game in games if game.state == "scheduled" and game.start_time >= now]
        if future:
            seconds_until = (min(future) - now).total_seconds()
            if seconds_until <= 15 * 60:
                return self.live_refresh_seconds
            if seconds_until <= 24 * 60 * 60:
                return 300
        if any(game.is_final and (now - game.start_time).total_seconds() < 12 * 60 * 60 for game in games):
            return 900
        return 3600

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        if response.status_code == 429:
            raise ProviderError("rate limit reached")
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("provider returned invalid JSON") from exc
