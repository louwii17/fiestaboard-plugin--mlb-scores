import json
from datetime import UTC, datetime
from pathlib import Path

from plugins.live_sports import LiveSportsPlugin
from plugins.live_sports.models import Game, Team
from plugins.live_sports.providers.base import ProviderError


def manifest():
    return json.loads((Path(__file__).parents[1] / "manifest.json").read_text())


def make_game(sport="MLB", state="live", favorite_name="Toronto Blue Jays", home_abbr="TOR"):
    return Game(
        id=f"{sport}-1", sport=sport, league=sport, source="stub",
        start_time=datetime(2026, 7, 14, 20, 0, tzinfo=UTC),
        state=state, status="Live", phase="LIVE", clock="10:00",
        home=Team("1", favorite_name, home_abbr, 3),
        away=Team("2", "Visitors", "VIS", 2),
        details={"inning": 7, "inning_half": "Top", "inning_ordinal": "7th", "outs": 1},
    )


class StubProvider:
    def __init__(self, games=None, error=None):
        self.games = games or []
        self.error = error
        self.cleared = False

    def get_games(self, now):
        if self.error:
            raise ProviderError(self.error)
        return self.games

    def clear_cache(self):
        self.cleared = True


def test_validate_config():
    plugin = LiveSportsPlugin(manifest())
    assert plugin.validate_config({"sports": ["MLB"], "timezone": "UTC"}) == []
    errors = plugin.validate_config({"sports": ["CRICKET"], "fifa_provider": "bad", "max_games_per_sport": 99, "timezone": "bad/time"})
    assert len(errors) == 4
    assert plugin.validate_config({"sports": ["FIFA"], "fifa_provider": "api_sports", "timezone": "UTC"})


def test_fetch_combines_sports_and_exposes_arrays(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB", "NHL"], "mlb_teams": "TOR", "timezone": "UTC"}
    providers = {"MLB": StubProvider([make_game("MLB")]), "NHL": StubProvider([make_game("NHL", "scheduled", "Montreal Canadiens")])}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: providers[key])
    result = plugin.fetch_data()
    assert result.available
    assert result.data["game_count"] == 2
    assert result.data["games"][0]["favorite"] is True
    assert result.data["games"][0]["away_short"] == "VIS"
    assert result.data["games"][0]["home_short"] == "TOR"
    assert result.data["games"][0]["home_color"] == "{67}"
    assert len(result.data["mlb"]) == 1
    assert len(result.formatted_lines) <= 6


def test_favorites_only_filters_games(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB"], "mlb_teams": "TOR", "favorites_only": True, "timezone": "UTC"}
    provider = StubProvider([make_game(), make_game(favorite_name="Boston Red Sox", home_abbr="BOS")])
    monkeypatch.setattr(plugin, "_provider_for", lambda key: provider)
    result = plugin.fetch_data()
    assert result.data["game_count"] == 1


def test_mlb_favorites_accept_array_config(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB"], "mlb_teams": ["TOR", "NYY"], "timezone": "UTC"}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: StubProvider([make_game()]))
    assert plugin.fetch_data().data["games"][0]["favorite"] is True


def test_live_favorite_emits_note_safe_trigger(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {
        "sports": ["MLB"],
        "mlb_teams": ["TOR"],
        "timezone": "UTC",
        "refresh_seconds": 10,
    }
    monkeypatch.setattr(plugin, "_provider_for", lambda key: StubProvider([make_game()]))
    triggers = plugin.check_triggers()
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger.trigger_id == "live_sports:mlb:MLB-1"
    assert trigger.priority == 50
    assert trigger.duration_seconds == 45
    assert trigger.data["away_short"] == "VIS"
    assert trigger.formatted_lines[0] == "TOP 7     1 OUT"
    assert trigger.formatted_lines[1] == "{67} VIS         2"


def test_non_live_favorite_does_not_trigger(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB"], "mlb_teams": ["TOR"], "timezone": "UTC"}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: StubProvider([make_game(state="final")]))
    assert plugin.check_triggers() == []


def test_one_provider_failure_does_not_hide_other_sport(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB", "NHL"], "timezone": "UTC"}
    providers = {"MLB": StubProvider(error="MLB offline"), "NHL": StubProvider([make_game("NHL")])}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: providers[key])
    result = plugin.fetch_data()
    assert result.available
    assert result.data["game_count"] == 1
    assert result.data["errors"] == ["MLB offline"]


def test_all_providers_failed_is_unavailable(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB"], "timezone": "UTC"}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: StubProvider(error="offline"))
    result = plugin.fetch_data()
    assert not result.available
    assert result.error == "offline"


def test_openligadb_falls_back_to_api_sports(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["FIFA"], "api_sports_key": "secret", "timezone": "UTC"}
    providers = {"FIFA:openligadb": StubProvider(error="offline"), "FIFA:api_sports": StubProvider([make_game("FIFA")])}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: providers[key])
    assert plugin._games_for("FIFA", datetime.now(UTC))[0].sport == "FIFA"


def test_config_change_clears_provider_cache():
    plugin = LiveSportsPlugin(manifest())
    provider = StubProvider()
    plugin._providers["MLB"] = provider
    plugin.config = {"sports": ["MLB"]}
    assert provider.cleared
    assert plugin._providers == {}


def test_no_games_is_available_with_empty_arrays(monkeypatch):
    plugin = LiveSportsPlugin(manifest())
    plugin.config = {"sports": ["MLB"], "timezone": "UTC"}
    monkeypatch.setattr(plugin, "_provider_for", lambda key: StubProvider())
    result = plugin.fetch_data()
    assert result.available and result.data["games"] == []
    assert result.formatted_lines == ["LIVE SPORTS", "NO GAMES TODAY"]
