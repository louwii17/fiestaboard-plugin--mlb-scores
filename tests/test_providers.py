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
    assert game.details["first_base_occupied"] is True
    assert game.details["second_base_occupied"] is False
    assert game.details["third_base_occupied"] is True
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


def test_mlb_treats_warmup_as_scheduled_and_hides_pregame_inning(fixture, fake_session):
    raw = fixture("mlb")["dates"][0]["games"][0]
    raw["status"] = {"abstractGameState": "Live", "detailedState": "Warmup"}
    raw["linescore"].update({
        "currentInning": 1,
        "currentInningOrdinal": "1st",
        "inningState": "Top",
    })

    game = MlbProvider(session=fake_session())._parse_game(raw)

    assert game.state == "scheduled"
    assert game.status == "Warmup"
    assert game.phase == "WARMUP"


def test_mlb_preserves_full_bottom_in_phase(fixture, fake_session):
    raw = fixture("mlb")["dates"][0]["games"][0]
    raw["linescore"].update({
        "currentInning": 1,
        "currentInningOrdinal": "1st",
        "inningState": "Bottom",
    })

    game = MlbProvider(session=fake_session())._parse_game(raw)

    assert game.phase == "BOTTOM 1ST"
    assert game.details["inning_half"] == "Bottom"


def test_mlb_skips_middle_ninth_when_home_team_has_already_won(fixture, fake_session):
    raw = fixture("mlb")["dates"][0]["games"][0]
    raw["status"] = {"abstractGameState": "Live", "detailedState": "In Progress"}
    raw["linescore"].update({
        "currentInning": 9,
        "currentInningOrdinal": "9th",
        "inningState": "Middle",
        "outs": 3,
    })
    raw["teams"]["home"]["score"] = 5
    raw["teams"]["away"]["score"] = 4

    game = MlbProvider(session=fake_session())._parse_game(raw)

    assert game.state == "live"
    assert game.phase == "FINAL"


def test_mlb_keeps_middle_ninth_when_home_team_is_not_ahead(fixture, fake_session):
    raw = fixture("mlb")["dates"][0]["games"][0]
    raw["status"] = {"abstractGameState": "Live", "detailedState": "In Progress"}
    raw["linescore"].update({
        "currentInning": 9,
        "currentInningOrdinal": "9th",
        "inningState": "Middle",
        "outs": 3,
    })
    raw["teams"]["home"]["score"] = 4
    raw["teams"]["away"]["score"] = 4

    game = MlbProvider(session=fake_session())._parse_game(raw)

    assert game.phase == "MIDDLE 9TH"


def test_mlb_clears_bases_at_three_outs(fixture, fake_session):
    raw = fixture("mlb")["dates"][0]["games"][0]
    raw["linescore"]["outs"] = 3
    game = MlbProvider(session=fake_session())._parse_game(raw)
    assert game.details["first_base_occupied"] is False
    assert game.details["second_base_occupied"] is False
    assert game.details["third_base_occupied"] is False


def test_base_provider_serves_stale_cache_on_failure(fixture, fake_session):
    provider = MlbProvider(session=fake_session(fixture("mlb"), RuntimeError("offline")))
    first = provider.get_games(NOW)
    provider._next_fetch_at = NOW
    assert provider.get_games(NOW) == first
    assert provider.last_error == "offline"
