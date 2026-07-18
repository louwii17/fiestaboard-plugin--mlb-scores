# MLB setup

## Requirements

- FiestaBoard 7.0 or newer.
- A Vestaboard Flagship or Note already connected to FiestaBoard.
- Outbound HTTPS access from the FiestaBoard server to
  `statsapi.mlb.com`.

No MLB account or API key is required.

## Install

1. Open FiestaBoard at `http://YOUR-SERVER:4420`.
2. Go to **Integrations**.
3. Choose **Install from Git**.
4. Paste the HTTPS URL for this repository.
5. Install and enable **Live Sports**.

For Docker installations, persist both directories:

```yaml
volumes:
  - ./data:/app/data
  - ./external_plugins:/app/external_plugins
```

## Configure MLB

1. Set **Sports** to **MLB**.
2. Select favorite teams under **Favorite MLB teams**.
3. Set the correct IANA timezone, such as `America/Toronto`.
4. Keep **Live refresh interval** at 10 seconds initially.
5. Save the integration.

## Create a Vestaboard Note page

Create a template page with these three lines:

```text
{{live_sports.inning_info}}
{{live_sports.away_color}} {{live_sports.away_short}} {{live_sports.away_score}}
{{live_sports.home_color}} {{live_sports.home_short}} {{live_sports.home_score}}
```

Set all three lines to center alignment with wrapping disabled. Save the page,
return to **Integrations → Live Sports**, and choose it under **Live game
page**.

## Verify

Normal page data can be previewed in FiestaBoard's page editor. Trigger checks
can also be forced through the local API:

```bash
curl -X POST http://YOUR-SERVER:4420/api/triggers/check
curl http://YOUR-SERVER:4420/api/triggers/active
```

A takeover only occurs when a selected favorite team's game is reported as
live. Silence mode still suppresses plugin-triggered pages. A manual page
change dismisses and temporarily suppresses the active trigger.

## Update

Use FiestaBoard's integration update control when available. For a manually
copied installation, pull or replace the `external_plugins/live_sports`
folder and restart FiestaBoard.
