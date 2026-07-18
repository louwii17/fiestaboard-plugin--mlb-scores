from datetime import UTC, datetime

import pytest

from plugins.live_sports.providers import ApiSportsFifaProvider, MlbProvider, NhlProvider, OpenLigaDbProvider
from plugins.live_sports.providers.base import BaseProvider, ProviderError

NOW = datetime(2026, 7, 14, 22, 0, tzinfo=UTC)


def test_mlb_normalizes_live_game(fixture, fake_session):
    session = fake_session(fixture("mlb"))
    games = MlbProvider(session=session, timezone_name="America/Toronto").get_games(NOW)
    game = games[0]
    assert (game.sport, game.state, game.phase) == ("MLB", "live", "TOP 7TH")
    assert (game.away.abbreviation, game.away.score) == ("TOR", 4)
    assert (game.away.short_name, game.home.short_name) == ("Blue Jays", "Yankees")
    assert session.calls[0][1]["params"]["sportId"] == 1
    assert session.calls[0][1]["params"]["startDate"] == "2026-07-13"
    assert session.calls[0][1]["params"]["endDate"] == "2026-07-15"


def test_nhl_normalizes_period_and_clock(fixture, fake_session):
    game = NhlProvider(session=fake_session(fixture("nhl"))).get_games(NOW)[0]
    assert game.state == "live"
    assert game.phase == "2ND"
    assert game.clock == "12:30"
    assert game.home.abbreviation == "MTL"


def test_openligadb_normalizes_finished_world_cup_game(fixture, fake_session):
    game = OpenLigaDbProvider(session=fake_session(fixture("openligadb"))).get_games(NOW)[0]
    assert game.sport == "FIFA"
    assert game.state == "final"
    assert game.home.name == "Canada"
    assert (game.home.score, game.away.score) == (2, 1)


def test_api_sports_requires_key():
    with pytest.raises(ProviderError, match="key is required"):
        ApiSportsFifaProvider(api_key="").get_games(NOW)


def test_api_sports_normalizes_live_fixture(fixture, fake_session):
    session = fake_session(fixture("api_sports"))
    game = ApiSportsFifaProvider(api_key="secret", session=session).get_games(NOW)[0]
    assert (game.state, game.phase, game.clock) == ("live", "2H", "72'")
    assert session.calls[0][1]["headers"] == {"x-apisports-key": "secret"}


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
    # Cached calls do not consume another HTTP payload.
    assert len(provider.get_games(NOW)) == 1


def test_mlb_live_refresh_can_be_ten_seconds(fixture, fake_session):
    provider = MlbProvider(
        session=fake_session(fixture("mlb")),
        live_refresh_seconds=10,
    )
    provider.get_games(NOW)
    assert (provider._next_fetch_at - NOW).total_seconds() == 10


def test_openligadb_refreshes_active_match(fixture, fake_session):
    scheduled = fixture("openligadb")[0]
    scheduled["matchIsFinished"] = False
    scheduled["matchDateTimeUTC"] = "2026-07-14T21:00:00Z"
    live = {**scheduled, "matchResults": [], "goals": [{"scoreTeam1": 1, "scoreTeam2": 0}]}
    session = fake_session([scheduled], live)
    provider = OpenLigaDbProvider(session=session)
    game = provider.get_games(NOW)[0]
    assert game.state == "live"
    assert game.home.score == 1
    assert len(session.calls) == 2
    provider.clear_cache()
    assert provider._raw_schedule == []


def test_mlb_and_nhl_status_variants(fixture, fake_session):
    mlb_raw = fixture("mlb")["dates"][0]["games"][0]
    provider = MlbProvider(session=fake_session())
    mlb_raw["status"] = {"abstractGameState": "Final", "detailedState": "Final"}
    assert provider._parse_game(mlb_raw).state == "final"
    mlb_raw["status"] = {"abstractGameState": "Preview", "detailedState": "Postponed"}
    assert provider._parse_game(mlb_raw).state == "postponed"

    nhl_raw = fixture("nhl")["games"][0]
    nhl_raw["clock"]["inIntermission"] = True
    assert NhlProvider(session=fake_session())._parse_game(nhl_raw).state == "intermission"
    nhl_raw["gameState"] = "OFF"
    nhl_raw["gameOutcome"] = {"lastPeriodType": "OT"}
    assert NhlProvider(session=fake_session())._parse_game(nhl_raw).phase == "FINAL/OT"


def test_api_sports_final_and_error_payload(fixture, fake_session):
    raw = fixture("api_sports")["response"][0]
    raw["fixture"]["status"] = {"long": "Match Finished", "short": "FT", "elapsed": 90}
    assert ApiSportsFifaProvider(api_key="key")._parse_game(raw).state == "final"
    with pytest.raises(ProviderError, match="quota"):
        ApiSportsFifaProvider(api_key="key", session=fake_session({"errors": {"limit": "quota"}})).get_games(NOW)


def test_base_provider_serves_stale_cache_on_failure(fixture, fake_session):
    provider = MlbProvider(session=fake_session(fixture("mlb"), RuntimeError("offline")))
    first = provider.get_games(NOW)
    provider._next_fetch_at = NOW
    assert provider.get_games(NOW) == first
    assert provider.last_error == "offline"
