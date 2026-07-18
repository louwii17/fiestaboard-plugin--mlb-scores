from datetime import UTC, datetime

from plugins.live_sports.formatting import board_text, format_progress, format_score, result_colors, team_abbreviation
from plugins.live_sports.models import Game, Team, as_int, parse_datetime


def game(state="live", home_score=3, away_score=4):
    return Game(
        id="1", sport="MLB", league="MLB", source="test",
        start_time=datetime(2026, 7, 14, 23, 7, tzinfo=UTC),
        state=state, status="In Progress", phase="TOP 7TH", clock="",
        home=Team("1", "New York Yankees", "NYY", home_score),
        away=Team("2", "Toronto Blue Jays", "TOR", away_score),
    )


def test_board_text_and_abbreviations():
    assert board_text("Côte d’Ivoire & USA!") == "COTE DIVOIRE AND USA"
    assert team_abbreviation("Toronto Blue Jays") == "TOR"
    assert team_abbreviation("New York Yankees", "NYY") == "NYY"


def test_score_and_progress_fit_board():
    assert len(format_score(game(), 22)) == 22
    assert "4-3" in format_score(game(), 15)
    assert format_progress(game()) == "TOP 7TH"
    assert format_progress(game("final")) == "TOP 7TH"


def test_scheduled_progress_uses_timezone():
    assert "TUE" in format_progress(game("scheduled"), timezone_name="America/Toronto")


def test_result_colors_and_model_helpers():
    assert result_colors(game()) == ("{66}", "{63}")
    assert result_colors(game(home_score=2, away_score=2)) == ("{65}", "{65}")
    assert as_int("7") == 7
    assert as_int("bad") is None
    assert parse_datetime("2026-07-14T12:00:00Z").tzinfo is not None
    assert game().is_live


def test_unknown_state_is_normalized():
    assert game("something-new").state == "unknown"
