"""Split-flap-friendly formatting helpers."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Game

TEAM_ALIASES = {
    "UNITED STATES": "USA",
    "SOUTH KOREA": "KOR",
    "KOREA REPUBLIC": "KOR",
    "COTE D'IVOIRE": "CIV",
    "IVORY COAST": "CIV",
    "BOSNIA AND HERZEGOVINA": "BIH",
    "TORONTO BLUE JAYS": "TOR",
    "MONTREAL CANADIENS": "MTL",
}

# Vestaboard has six colour tiles: red, orange, yellow, green, blue, and
# violet. These are deliberately approximate franchise colours; templates
# can use the result-colour fields instead when win/loss colouring is wanted.
TEAM_COLORS = {
    ("MLB", "ARI"): "{63}",
    ("MLB", "ATH"): "{66}",
    ("MLB", "OAK"): "{66}",
    ("MLB", "ATL"): "{63}",
    ("MLB", "BAL"): "{64}",
    ("MLB", "BOS"): "{63}",
    ("MLB", "CHC"): "{67}",
    ("MLB", "CWS"): "{67}",
    ("MLB", "CIN"): "{63}",
    ("MLB", "CLE"): "{63}",
    ("MLB", "COL"): "{68}",
    ("MLB", "DET"): "{67}",
    ("MLB", "HOU"): "{64}",
    ("MLB", "KC"): "{67}",
    ("MLB", "LAA"): "{63}",
    ("MLB", "LAD"): "{67}",
    ("MLB", "MIA"): "{67}",
    ("MLB", "MIL"): "{67}",
    ("MLB", "MIN"): "{63}",
    ("MLB", "NYM"): "{64}",
    ("MLB", "NYY"): "{67}",
    ("MLB", "PHI"): "{63}",
    ("MLB", "PIT"): "{65}",
    ("MLB", "SD"): "{65}",
    ("MLB", "SEA"): "{66}",
    ("MLB", "SF"): "{64}",
    ("MLB", "STL"): "{63}",
    ("MLB", "TB"): "{67}",
    ("MLB", "TEX"): "{67}",
    ("MLB", "TOR"): "{67}",
    ("MLB", "WSH"): "{63}",
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


def team_color(sport: str, abbreviation: str) -> str:
    """Return the closest Vestaboard tile for a franchise's primary colour."""
    return TEAM_COLORS.get((board_text(sport), board_text(abbreviation)), "{67}")
