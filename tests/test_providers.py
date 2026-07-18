from datetime import UTC, datetime

import pytest

from plugins.mlb_scores.providers import MlbProvider
from plugins.mlb_scores.providers.base import BaseProvider, ProviderError

NOW = datetime(2026, 7, 14, 22, 0, tzinfo=UTC)


def test_mlb_normalizes_live_game(fixture, fake_session):
    session = fake_session(fixture("mlb"))
    game = MlbProvider(session=session, timezone_name="America/Toronto").get_games(NOW)[0]
    assert (game.sport, game.state, game.phase) == ("MLB", "live", "TOP 7TH")
    assert (game.away.abbreviation, game.away.score) == ("TOR", 4)
    assert (game.away.short_name, game.home.short_name) == ("Blue Jays", "Yankees")
    assert session.calls[0][1]["params"]["sportId"] == 1
    assert session.calls[0][1]["params"]["startDate"] == "2026-07-13"
    assert session.calls[0][1]["params"]["endDate"] == "2026-07-15"


class FailingProvider(BaseProvider):
    name = "failure"

    def fetch_games(self, now):
        raise RuntimeError("offline")


def test_base_provider_wraps_errors_and_caches_failures():
    provider = FailingProvider()
    with pytest.raises(ProviderError, match="offline"):
        provider.get_games(NOW)
    assert provider.last_error == "offline"


def test_base_provider_adaptive_ttl(fixture, fake_session):
    provider = MlbProvider(session=fake_session(fixture("mlb")))
    provider.get_games(NOW)
    assert (provider._next_fetch_at - NOW).total_seconds() == 60
    assert len(provider.get_games(NOW)) == 1


def test_mlb_live_refresh_can_be_ten_seconds(fixture, fake_session):
    provider = MlbProvider(session=fake_session(fixture("mlb")), live_refresh_seconds=10)
    provider.get_games(NOW)
    assert (provider._next_fetch_at - NOW).total_seconds() == 10


def test_mlb_status_variants(fixture, fake_session):
    raw = fixture("mlb")["dates"][0]["games"][0]
    provider = MlbProvider(session=fake_session())
    raw["status"] = {"abstractGameState": "Final", "detailedState": "Final"}
    assert provider._parse_game(raw).state == "final"
    raw["status"] = {"abstractGameState": "Preview", "detailedState": "Postponed"}
    assert provider._parse_game(raw).state == "postponed"


def test_base_provider_serves_stale_cache_on_failure(fixture, fake_session):
    provider = MlbProvider(session=fake_session(fixture("mlb"), RuntimeError("offline")))
    first = provider.get_games(NOW)
    provider._next_fetch_at = NOW
    assert provider.get_games(NOW) == first
    assert provider.last_error == "offline"
