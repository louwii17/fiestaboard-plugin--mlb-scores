# Live Sports for FiestaBoard

An installable FiestaBoard 7+ plugin for fast, customizable live sports
pages. The first complete integration is MLB: favorite-team selection,
10-second live refreshes, Note/Flagship template variables, franchise colour
tiles, and automatic page takeover while a favorite game is in progress.

One FiestaBoard plugin with separate provider adapters for live and scheduled
scores. It currently supports:

- MLB via the free, unauthenticated MLB Stats API.
- NHL via the free, unauthenticated NHL GameCenter API.
- FIFA World Cup 2026 via OpenLigaDB by default.
- FIFA World Cup 2026 via API-Sports as an optional keyed provider or fallback.

The plugin exposes one normalized `games` array plus `fifa`, `mlb`, and `nhl`
arrays. This keeps FiestaBoard templates stable even though each league has a
different upstream API.

MLB data comes directly from MLB's public Stats API and requires no account or
API key. The integration polls adaptively: slowly when no game is near, and at
the configured interval (10 seconds by default) near first pitch and while a
game is live. FiestaBoard only sends changed content to the board.

## Easiest installation: Git URL

Push this directory to a public Git repository, then open FiestaBoard and use
**Integrations → Install from Git**. Paste the repository's HTTPS URL, install
it, and enable **Live Sports**.

The equivalent API request is:

```bash
curl -X POST http://YOUR-FIESTABOARD:4420/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"repository":"https://github.com/YOUR-NAME/fiestaboard-plugin--live-sports"}'
```

FiestaBoard clones external plugins into `/app/external_plugins`. Persist that
directory in Docker alongside `/app/data` so the plugin survives container
replacement.

## Install by copying the folder

The folder installed into FiestaBoard must be named `live_sports` because the
folder name and manifest ID must match when it is copied manually.

```bash
cd /path/to/FiestaBoard/external_plugins
git clone YOUR_REPOSITORY_URL live_sports
```

Alternatively, copy this project from another computer:

```bash
rsync -av --exclude '.git' fiestaboard-plugin--live-sports/ \
  user@server:/path/to/FiestaBoard/external_plugins/live_sports/
```

Restart FiestaBoard using the same method used for its initial deployment,
then enable **Live Sports** in the plugin settings.

## Configuration

For the initial MLB setup:

1. Select only **MLB** under Sports.
2. Choose one or more favorite MLB teams.
3. Keep **Live refresh interval** at 10 seconds.
4. Set the timezone used for game-day discovery.
5. Create a template page for the live game.
6. Return to the integration and select it under **Live game page**.

MLB favorites use a team picker. FIFA and NHL favorites currently accept
comma-separated names or abbreviations. `favorites_only` controls normal page
data; only favorite MLB games can trigger an automatic takeover.

Use an IANA timezone such as `America/Toronto`. Provider-level caching
automatically backs off when no game is live.

## Template examples

Vestaboard Note (15 × 3), inning on top:

```text
{{live_sports.inning_info}}
{{live_sports.away_color}} {{live_sports.away_short}} {{live_sports.away_score}}
{{live_sports.home_color}} {{live_sports.home_short}} {{live_sports.home_score}}
```

Or move `inning_info` to the third line. Each value is independent, so the
page editor controls ordering, spacing, alignment, and whether franchise or
win/loss colors are used.

Useful MLB building blocks:

```text
{{live_sports.away_color}}
{{live_sports.away_result_color}}
{{live_sports.away_short}}
{{live_sports.away_name}}
{{live_sports.away_nickname}}
{{live_sports.away_score}}
{{live_sports.home_color}}
{{live_sports.home_result_color}}
{{live_sports.home_short}}
{{live_sports.home_name}}
{{live_sports.home_nickname}}
{{live_sports.home_score}}
{{live_sports.inning_half}}
{{live_sports.inning_number}}
{{live_sports.inning_ordinal}}
{{live_sports.outs}}
{{live_sports.outs_text}}
{{live_sports.inning_info}}
```

The franchise color fields are approximations using Vestaboard's six color
tiles. The result color fields are green for winning, red for losing, yellow
for tied, and blue before scores are available.

Generic score lines remain available:

```text
{{live_sports.games[0].formatted}}
{{live_sports.games[0].progress}}
```

The compatibility variables `team1`, `team2`, `score1`, and `score2` refer to
the away and home teams of the highest-priority game. Live games sort first,
then upcoming games, then completed games.

## Development tests

Copy or clone the plugin into a FiestaBoard checkout at
`plugins/live_sports`, then run:

```bash
python scripts/run_plugin_tests.py --plugin=live_sports --verbose
```

No real API calls or credentials are used by the test suite.

## API note

These endpoints are not guaranteed service-level agreements. MLB and NHL are
public first-party endpoints; OpenLigaDB is community-operated. Keep the
optional API-Sports path configured if FIFA uptime is especially important.
