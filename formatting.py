"""Split-flap-friendly formatting helpers."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Game

TEAM_ALIASES = {
    "TORONTO BLUE JAYS": "TOR",
}

# MLB's official team stylesheets publish ordered decorative colors at
# https://brand-colors.mlbstatic.com/v1/team-{team_id}.css. Each entry below
# uses the closest useful Vestaboard tile to the club's first or second color.
# A bright secondary is preferred when a dark primary (navy, black, or brown)
# has no faithful color-tile equivalent on the board.
TEAM_COLORS = {
    "ARI": "{63}", "ATH": "{66}", "OAK": "{66}", "ATL": "{63}",
    "BAL": "{64}", "BOS": "{63}", "CHC": "{67}", "CWS": "{69}",
    "CIN": "{63}", "CLE": "{63}", "COL": "{68}", "DET": "{64}",
    "HOU": "{64}", "KC": "{67}", "LAA": "{63}", "LAD": "{67}",
    "MIA": "{67}", "MIL": "{65}", "MIN": "{63}", "NYM": "{64}",
    "NYY": "{67}", "PHI": "{63}", "PIT": "{65}", "SD": "{65}",
    "SEA": "{66}", "SF": "{64}", "STL": "{63}", "TB": "{67}",
    "TEX": "{67}", "TOR": "{67}", "WSH": "{63}",
}


def board_text(value: str) -> str:
    """Return uppercase ASCII text suitable for a split-flap display."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.upper().replace("&", "AND")
    value = re.sub(r"[^A-Z0-9 .:'/-]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def team_abbreviation(name: str, provided: str = "", max_length: int = 4) -> str:
    """Choose a stable, compact team abbreviation."""
    clean_name = board_text(name)
    clean_provided = board_text(provided)
    if clean_name in TEAM_ALIASES:
        return TEAM_ALIASES[clean_name][:max_length]
    if clean_provided and len(clean_provided) <= max_length:
        return clean_provided
    words = [word for word in clean_name.split() if word not in {"FC", "CF", "THE"}]
    if len(words) >= 2:
        acronym = "".join(word[0] for word in words if word)
        if 2 <= len(acronym) <= max_length:
            return acronym
        return (words[-1] if len(words[-1]) <= max_length else acronym[:max_length])
    return clean_name[:max_length]


def format_score(game: Game, width: int = 20) -> str:
    """Format away/home score on a single fixed-width line."""
    width = max(8, width)
    team_width = 4 if width >= 15 else 3
    away = team_abbreviation(game.away.name, game.away.abbreviation, team_width)
    home = team_abbreviation(game.home.name, game.home.abbreviation, team_width)
    away_score = "?" if game.away.score is None else str(game.away.score)
    home_score = "?" if game.home.score is None else str(game.home.score)
    middle = f"{away_score}-{home_score}"
    available = width - len(middle) - 2
    left_width = max(2, available // 2)
    right_width = max(2, available - left_width)
    rendered = f"{away[:left_width].ljust(left_width)} {middle} {home[:right_width].rjust(right_width)}"
    return rendered[:width].ljust(width)


def format_progress(game: Game, width: int = 22, timezone_name: str = "UTC") -> str:
    """Format a compact game-state line."""
    if game.state == "scheduled":
        try:
            local = game.start_time.astimezone(ZoneInfo(timezone_name))
        except Exception:
            local = game.start_time
        text = local.strftime("%a %I:%M %p").replace(" 0", " ")
    elif game.state == "final":
        text = game.phase or game.status or "FINAL"
    elif game.state == "intermission":
        text = game.phase or "INTERMISSION"
    elif game.state == "live":
        parts = [game.phase, game.clock]
        text = " ".join(part for part in parts if part) or "LIVE"
    else:
        text = game.status or game.state
    return board_text(text)[:width]


def game_datetime(game: Game, timezone_name: str = "UTC") -> tuple[str, str]:
    """Return local date and time strings for template variables."""
    try:
        local: datetime = game.start_time.astimezone(ZoneInfo(timezone_name))
    except Exception:
        local = game.start_time
    return local.strftime("%Y-%m-%d"), local.strftime("%I:%M %p").lstrip("0")


def result_colors(game: Game) -> tuple[str, str]:
    """Return FiestaBoard result color tiles for away and home teams."""
    if not game.has_scores or game.home.score == game.away.score:
        color = "{65}" if game.has_scores else "{67}"
        return color, color
    if (game.home.score or 0) > (game.away.score or 0):
        return "{63}", "{66}"
    return "{66}", "{63}"


def team_color(abbreviation: str) -> str:
    """Return the closest Vestaboard tile for a franchise's primary colour."""
    return TEAM_COLORS.get(board_text(abbreviation), "{67}")


def indicator_cell(value: object, default: str) -> str:
    """Return one literal board character or one numeric VBML character code."""
    text = str(value) if value is not None else ""
    if len(text) == 1:
        return text
    match = re.fullmatch(r"\{(\d{1,2})\}", text)
    if match and 0 <= int(match.group(1)) <= 71:
        return text
    return default


def outs_indicator(outs: int | None, on: str = "{69}", off: str = ".") -> str:
    """Return a configurable three-position indicator for the outs."""
    if outs is None:
        return ""
    recorded = max(0, min(3, outs))
    return on * recorded + off * (3 - recorded)
