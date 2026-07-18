# MLB Scores setup

## Requirements

- FiestaBoard 7.0 or newer.
- A Vestaboard Flagship or Note connected to FiestaBoard.
- Outbound HTTPS access to `statsapi.mlb.com`.

No MLB account or API key is required.

## Install

1. Open FiestaBoard at `http://YOUR-SERVER:4420`.
2. Go to **Integrations → Install from Git**.
3. Enter `https://github.com/louwii17/fiestaboard-plugin--mlb-scores`.
4. Select the `main` branch.
5. Install and enable **MLB Scores**.

For Docker installations, persist both directories:

```yaml
volumes:
  - ./data:/app/data
  - ./external_plugins:/app/external_plugins
```

## Configure

1. Select favorite teams.
2. Set the correct IANA timezone, such as `America/Toronto`.
3. Keep **Live refresh interval** at 10 seconds initially.
4. Save the integration.

## Create a Vestaboard Note page

Create a template page with these three lines:

```text
{{= PAD(UPPER(mlb_scores.inning_half) & " " & mlb_scores.inning_number, 9) & PADLEFT(mlb_scores.outs & IF(mlb_scores.outs = 1, " OUT", " OUTS"), 6) }}
{{= mlb_scores.away_color & " " & PAD(mlb_scores.away_nickname, 11) & PADLEFT(mlb_scores.away_score, 2) }}
{{= mlb_scores.home_color & " " & PAD(mlb_scores.home_nickname, 11) & PADLEFT(mlb_scores.home_score, 2) }}
```

Set all lines to left alignment with wrapping disabled. Save the page, return
to **Integrations → MLB Scores**, and select it under **Live game page**.

## Verify

Force a trigger check through the local API:

```bash
curl -X POST http://YOUR-SERVER:4420/api/triggers/check
curl http://YOUR-SERVER:4420/api/triggers/active
```

A takeover occurs only when a selected favorite team's game is reported as
live. Silence mode suppresses plugin triggers. A manual page change dismisses
and temporarily suppresses an active trigger.

## Update

Pull the latest code and restart FiestaBoard:

```bash
git -C /mnt/docker/fiestaboard-plugins/mlb_scores pull --ff-only
docker restart fiestaboard
```
