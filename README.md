# MLB Scores for FiestaBoard

An installable FiestaBoard 7+ plugin for fast, customizable MLB pages on a
Vestaboard Flagship or Note.

## Features

- Free MLB Stats API; no account or API key.
- Favorite-team selection for all 30 MLB clubs.
- 10-second refreshes near first pitch and while a game is live.
- Adaptive caching when no live game is near.
- Automatic FiestaBoard page takeover for live favorite games.
- Separate full name, nickname, abbreviation, score, color, inning, and outs
  variables for custom pages.
- Team tiles derived from MLB's official first and second brand colors and
  mapped to the closest useful Vestaboard color.
- Franchise-color and win/loss-color tiles.
- Template-controlled live-game triggers with no competing hardcoded layout.
- Stale-cache fallback during temporary MLB API failures.

## Install from Git

In FiestaBoard, open **Integrations → Install from Git** and enter:

```text
https://github.com/louwii17/fiestaboard-plugin--mlb-scores
```

Use the `main` branch, install the plugin, and enable **MLB Scores**.

The equivalent API request is:

```bash
curl -X POST http://YOUR-FIESTABOARD:4420/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"repository":"https://github.com/louwii17/fiestaboard-plugin--mlb-scores","branch":"main"}'
```

For a manual clone, the directory must match the plugin ID:

```bash
git clone https://github.com/louwii17/fiestaboard-plugin--mlb-scores.git mlb_scores
```

Persist FiestaBoard's external plugin directory in Docker:

```yaml
volumes:
  - ./data:/app/data
  - ./external_plugins:/app/external_plugins
```

## Configure

1. Enable **MLB Scores**.
2. Choose one or more favorite teams.
3. Set the correct IANA timezone, such as `America/Toronto`.
4. Keep **Live refresh interval** at 10 seconds initially.
5. Create a template page for the live game.
6. Select it under **Live game page**.

Only favorite games trigger a takeover. `favorites_only` controls whether
non-favorite games remain available to ordinary MLB pages.

The live trigger supplies fresh `mlb_scores` variables to the selected page
without a hardcoded display fallback, so updates retain the page's names,
alignment, and indicators. If the selected page is missing or invalid, the
trigger leaves the current display unchanged.

## Vestaboard Note template

This 15 × 3 template keeps the outs and scores on the trailing edge, uses
city-free team nicknames, and reserves two cells for each score:

```text
{{= PAD(UPPER(mlb_scores.inning_half) & " " & mlb_scores.inning_ordinal, 12) & mlb_scores.outs_color_indicator }}
{{= mlb_scores.away_color & " " & PAD(mlb_scores.away_nickname, 11) & PADLEFT(mlb_scores.away_score, 2) }}
{{= mlb_scores.home_color & " " & PAD(mlb_scores.home_nickname, 11) & PADLEFT(mlb_scores.home_score, 2) }}
```

Set every line to left alignment with wrapping disabled.

## Template variables

Useful building blocks include:

```text
{{mlb_scores.away_color}}
{{mlb_scores.away_result_color}}
{{mlb_scores.away_short}}
{{mlb_scores.away_name}}
{{mlb_scores.away_nickname}}
{{mlb_scores.away_score}}
{{mlb_scores.home_color}}
{{mlb_scores.home_result_color}}
{{mlb_scores.home_short}}
{{mlb_scores.home_name}}
{{mlb_scores.home_nickname}}
{{mlb_scores.home_score}}
{{mlb_scores.inning_half}}
{{mlb_scores.inning_number}}
{{mlb_scores.inning_ordinal}}
{{mlb_scores.outs}}
{{mlb_scores.outs_text}}
{{mlb_scores.outs_color_indicator}}
{{mlb_scores.outs_symbol_indicator}}
{{mlb_scores.first_base_occupied}}
{{mlb_scores.second_base_occupied}}
{{mlb_scores.third_base_occupied}}
{{mlb_scores.first_base_indicator}}
{{mlb_scores.second_base_indicator}}
{{mlb_scores.third_base_indicator}}
{{mlb_scores.inning_info}}
```

Each base indicator is a yellow tile (`{65}`) when occupied and a dash when
empty. The matching Boolean can be used with `IF()` for a custom color or
placeholder. To draw the traditional diamond yourself, place second base above
third and first base:

```text
{{= PAD("", 7) & mlb_scores.second_base_indicator }}
{{= PAD("", 5) & mlb_scores.third_base_indicator & " " & mlb_scores.first_base_indicator }}
```

The three-position outs indicators render as follows:

| Outs | Color tiles | Symbols |
| --- | --- | --- |
| 0 | `---` | `---` |
| 1 | `{69}--` | `O--` |
| 2 | `{69}{69}-` | `OO-` |
| 3 | `{69}{69}{69}` | `OOO` |

Use the explicit `away_*` and `home_*` fields so the side and display format
remain unambiguous across live updates. Multiple games are available under
`mlb_scores.games`.

## Development tests

Copy or clone the repository into a FiestaBoard checkout at
`plugins/mlb_scores`, then run:

```bash
python scripts/run_plugin_tests.py --plugin=mlb_scores --verbose
```

No real API calls are used by the test suite.

## API note

MLB's Stats API is public and unauthenticated but does not provide a formal
service-level agreement. The plugin uses adaptive caching, request timeouts,
and stale results to avoid blanking a live page during brief outages.
