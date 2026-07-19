import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.mlb_scores import MlbScoresPlugin
from plugins.mlb_scores.models import Game, Team
from plugins.mlb_scores.providers.base import ProviderError


def manifest():
    return json.loads((Path(__file__).parents[1] / "manifest.json").read_text())


@pytest.fixture(autouse=True)
def fixed_plugin_time(monkeypatch):
    monkeypatch.setattr(
        MlbScoresPlugin,
        "_now",
        lambda self: datetime(2026, 7, 14, 23, 0, tzinfo=UTC),
    )


def make_game(state="live", favorite_name="Toronto Blue Jays", home_abbr="TOR"):
    is_final = state == "final"
    return Game(
        id="MLB-1", sport="MLB", league="MLB", source="stub",
        start_time=datetime(2026, 7, 14, 20, 0, tzinfo=UTC),
        state=state, status="Final" if is_final else "Live", phase="FINAL" if is_final else "TOP 7TH", clock="",
        home=Team("1", favorite_name, home_abbr, 3, "Blue Jays"),
        away=Team("2", "New York Yankees", "NYY", 2, "Yankees"),
        details={
            "inning": 7, "inning_half": "Top", "inning_ordinal": "7th", "outs": 1,
            "first_base_occupied": True, "second_base_occupied": False,
            "third_base_occupied": True,
        },
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
    plugin = MlbScoresPlugin(manifest())
    assert plugin.validate_config({"favorite_teams": ["TOR"], "timezone": "UTC"}) == []
    errors = plugin.validate_config({"favorite_teams": 42, "timezone": "bad/time"})
    assert len(errors) == 2
    assert plugin.validate_config({"timezone": "UTC", "outs_indicator_off": "{0}"}) == []
    assert plugin.validate_config({"timezone": "UTC", "outs_indicator_on": "TOO LONG"}) == [
        "outs_indicator_on must be one character, {0} for blank, or a color code from {63} to {71}"
    ]
    assert plugin.validate_config({"timezone": "UTC", "final_display_seconds": 5}) == [
        "Final score display time must be between 10 and 900 seconds"
    ]
    assert plugin.validate_config({"timezone": "UTC", "delay_display_seconds": 1801}) == [
        "Delayed game display time must be between 0 and 1800 seconds"
    ]


def test_fetch_exposes_mlb_building_blocks(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC"}
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([make_game()]))
    result = plugin.fetch_data()
    assert result.available
    assert result.data["game_count"] == 1
    assert result.data["favorite"] is True
    assert result.data["away_short"] == "NYY"
    assert result.data["away_nickname"] == "YANKEES"
    assert result.data["home_short"] == "TOR"
    assert result.data["home_nickname"] == "BLUE JAYS"
    assert result.data["home_color"] == "{67}"
    assert result.data["inning_number"] == 7
    assert result.data["inning_info"] == "TOP 7 1 OUT"
    assert result.data["outs_indicator"] == "{69}.."
    assert result.data["first_base_occupied"] is True
    assert result.data["second_base_occupied"] is False
    assert result.data["third_base_occupied"] is True
    assert result.data["first_base_indicator"] == "{65}"
    assert result.data["second_base_indicator"] == "."
    assert result.data["third_base_indicator"] == "{65}"
    assert "team1" not in result.data
    assert "team2" not in result.data
    assert "score1" not in result.data
    assert "score2" not in result.data


def test_fetch_exposes_full_and_short_phase(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC"}
    game = make_game()
    game.phase = "BOTTOM 1ST"
    game.details["inning_half"] = "Bottom"
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([game]))

    result = plugin.fetch_data()

    assert result.data["phase"] == "BOTTOM 1ST"
    assert result.data["phase_short"] == "BOT 1ST"
    assert result.data["inning_half"] == "BOTTOM"
    assert result.data["inning_half_short"] == "BOT"

    game.phase = "MIDDLE 1ST"
    game.details["inning_half"] = "Middle"
    result = plugin.fetch_data()

    assert result.data["phase"] == "MIDDLE 1ST"
    assert result.data["phase_short"] == "MID 1ST"
    assert result.data["inning_half"] == "MIDDLE"
    assert result.data["inning_half_short"] == "MID"


def test_custom_indicator_markers(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {
        "favorite_teams": ["TOR"],
        "timezone": "UTC",
        "outs_indicator_on": "X",
        "outs_indicator_off": "-",
        "base_indicator_on": "{66}",
        "base_indicator_off": " ",
    }
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([make_game()]))
    result = plugin.fetch_data()
    assert result.data["outs_indicator"] == "X--"
    assert result.data["first_base_indicator"] == "{66}"
    assert result.data["second_base_indicator"] == " "


def test_blank_character_code_renders_as_one_open_out_cell(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {
        "favorite_teams": ["TOR"],
        "timezone": "UTC",
        "outs_indicator_off": "{0}",
    }
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([make_game()]))

    result = plugin.fetch_data()

    assert result.data["outs_indicator"] == "{69}  "


def test_effective_final_phase_replaces_middle_inning_info(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC"}
    game = make_game()
    game.phase = "FINAL"
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([game]))

    result = plugin.fetch_data()

    assert result.data["state"] == "live"
    assert result.data["phase"] == "FINAL"
    assert result.data["inning_info"] == "FINAL"


def test_favorites_only_filters_games(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "favorites_only": True, "timezone": "UTC"}
    games = [make_game(), make_game(favorite_name="Boston Red Sox", home_abbr="BOS")]
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider(games))
    result = plugin.fetch_data()
    assert result.data["game_count"] == 1


def test_fetch_returns_all_games_without_a_maximum(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC"}
    games = []
    for index in range(12):
        game = make_game(favorite_name=f"Team {index}", home_abbr=f"T{index}")
        game.id = f"MLB-{index:02d}"
        games.append(game)
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider(games))

    result = plugin.fetch_data()

    assert result.data["game_count"] == 12
    assert len(result.data["games"]) == 12


def test_page_data_uses_local_day_but_triggers_inspect_full_window(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["BOS"], "timezone": "UTC", "refresh_seconds": 10}
    today = make_game(state="scheduled")
    today.id = "TODAY"
    tomorrow = make_game(state="scheduled", favorite_name="Boston Red Sox", home_abbr="BOS")
    tomorrow.id = "TOMORROW"
    tomorrow.start_time += timedelta(days=1)
    tomorrow_live = make_game(favorite_name="Boston Red Sox", home_abbr="BOS")
    tomorrow_live.id = "TOMORROW-LIVE"
    tomorrow_live.start_time += timedelta(days=1)
    provider = StubProvider([today, tomorrow, tomorrow_live])
    monkeypatch.setattr(plugin, "_get_provider", lambda: provider)
    monkeypatch.setattr(plugin, "get_data", plugin.fetch_data)

    result = plugin.fetch_data()
    triggers = plugin.check_triggers()

    assert [game["game_id"] for game in result.data["games"]] == ["TOMORROW-LIVE", "TODAY"]
    assert [(trigger.trigger_id, trigger.data["game_id"]) for trigger in triggers] == [
        ("mlb_scores:BOS", "TOMORROW-LIVE")
    ]


def test_favorite_configuration_order_ranks_games_and_triggers(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {
        "favorite_teams": ["BOS", "TOR", "NYY"],
        "timezone": "UTC",
        "refresh_seconds": 10,
    }
    tor = make_game()
    tor.id = "TOR-GAME"
    bos = make_game(favorite_name="Boston Red Sox", home_abbr="BOS")
    bos.id = "BOS-GAME"
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([tor, bos]))

    result = plugin.fetch_data()
    triggers = plugin.check_triggers()

    assert [game["home_short"] for game in result.data["games"]] == ["BOS", "TOR"]
    assert [game["favorite_rank"] for game in result.data["games"]] == [0, 1]
    assert [(trigger.trigger_id, trigger.priority) for trigger in triggers] == [
        ("mlb_scores:BOS", 50),
        ("mlb_scores:TOR", 49),
    ]


def test_live_favorite_emits_note_safe_trigger(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC", "refresh_seconds": 10}
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([make_game()]))
    trigger = plugin.check_triggers()[0]
    assert trigger.trigger_id == "mlb_scores:TOR"
    assert trigger.priority == 50
    assert trigger.duration_seconds == 45
    assert trigger.data["home_nickname"] == "BLUE JAYS"
    assert trigger.formatted_lines is None
    assert trigger.message is None


def test_non_live_favorite_does_not_trigger(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC"}
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([make_game(state="final")]))
    assert plugin.check_triggers() == []


def test_warmup_favorite_does_not_trigger(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC"}
    game = make_game(state="scheduled")
    game.status = "Warmup"
    game.phase = "WARMUP"
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider([game]))

    result = plugin.fetch_data()
    assert result.data["state"] == "scheduled"
    assert result.data["status"] == "Warmup"
    assert result.data["phase"] == "WARMUP"
    assert plugin.check_triggers() == []


def test_live_to_final_holds_final_until_configured_deadline(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {
        "favorite_teams": ["TOR"],
        "timezone": "UTC",
        "refresh_seconds": 10,
        "final_display_seconds": 120,
    }
    provider = StubProvider([make_game()])
    now = [datetime(2026, 7, 14, 23, 0, tzinfo=UTC)]
    monkeypatch.setattr(plugin, "_now", lambda: now[0])
    monkeypatch.setattr(plugin, "_get_provider", lambda: provider)
    monkeypatch.setattr(plugin, "get_data", plugin.fetch_data)

    assert plugin.check_triggers()[0].data["state"] == "live"

    provider.games = [make_game(state="final")]
    final_trigger = plugin.check_triggers()[0]
    assert final_trigger.data["state"] == "final"
    assert final_trigger.data["phase"] == "FINAL"
    assert final_trigger.data["inning_info"] == "FINAL"
    assert final_trigger.duration_seconds == 120

    now[0] += timedelta(seconds=60)
    assert plugin.check_triggers()[0].duration_seconds == 60

    now[0] += timedelta(seconds=61)
    assert plugin.check_triggers() == []


def test_live_delay_uses_configured_grace_period(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {
        "favorite_teams": ["TOR"],
        "timezone": "UTC",
        "refresh_seconds": 10,
        "delay_display_seconds": 300,
    }
    provider = StubProvider([make_game()])
    now = [datetime(2026, 7, 14, 23, 0, tzinfo=UTC)]
    monkeypatch.setattr(plugin, "_now", lambda: now[0])
    monkeypatch.setattr(plugin, "_get_provider", lambda: provider)
    monkeypatch.setattr(plugin, "get_data", plugin.fetch_data)

    assert plugin.check_triggers()[0].data["state"] == "live"
    delayed = make_game(state="delayed")
    delayed.status = "Rain Delay"
    delayed.phase = "DELAYED"
    provider.games = [delayed]
    assert plugin.check_triggers()[0].duration_seconds == 45

    now[0] += timedelta(seconds=280)
    assert plugin.check_triggers()[0].duration_seconds == 20

    now[0] += timedelta(seconds=21)
    assert plugin.check_triggers() == []


def test_new_live_doubleheader_game_replaces_same_teams_final_hold(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"favorite_teams": ["TOR"], "timezone": "UTC", "refresh_seconds": 10}
    first = make_game()
    first.id = "GAME-1"
    provider = StubProvider([first])
    monkeypatch.setattr(plugin, "_get_provider", lambda: provider)
    monkeypatch.setattr(plugin, "get_data", plugin.fetch_data)

    assert plugin.check_triggers()[0].data["game_id"] == "GAME-1"
    first_final = make_game(state="final")
    first_final.id = "GAME-1"
    second = make_game()
    second.id = "GAME-2"
    second.start_time += timedelta(hours=4)
    provider.games = [first_final, second]

    trigger = plugin.check_triggers()[0]

    assert trigger.trigger_id == "mlb_scores:TOR"
    assert trigger.data["game_id"] == "GAME-2"
    assert trigger.data["state"] == "live"


def test_provider_failure_is_unavailable(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"timezone": "UTC"}
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider(error="offline"))
    result = plugin.fetch_data()
    assert not result.available
    assert result.error == "offline"


def test_config_change_clears_provider_cache():
    plugin = MlbScoresPlugin(manifest())
    provider = StubProvider()
    plugin._provider = provider
    plugin.config = {"favorite_teams": ["TOR"]}
    assert provider.cleared
    assert plugin._provider is None


def test_no_games_is_available_with_empty_array(monkeypatch):
    plugin = MlbScoresPlugin(manifest())
    plugin.config = {"timezone": "UTC"}
    monkeypatch.setattr(plugin, "_get_provider", lambda: StubProvider())
    result = plugin.fetch_data()
    assert result.available and result.data["games"] == []
    assert result.data["first_base_indicator"] == ""
    assert result.data["second_base_indicator"] == ""
    assert result.data["third_base_indicator"] == ""
    assert result.formatted_lines == ["MLB SCORES", "NO GAMES TODAY"]
