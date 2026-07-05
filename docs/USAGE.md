# Usage Guide

## Input Options

You can start monitoring in either of these ways:

- Place statements or normalized CSV files under `input/` and run `portfolio-monitor ingest input`.
- Provide files directly to your local assistant and ask it to ingest from those local file paths.

Private files should stay local. Do not commit statements, exports, generated reports, local databases, or screenshots containing account data.

## First Run

Import statements or normalized CSV files:

```bash
portfolio-monitor ingest input
```

Refresh prices online:

```bash
portfolio-monitor refresh-prices
```

If online prices are unavailable, import manual prices:

```bash
portfolio-monitor prices input/prices.csv
```

If cost basis is missing, import a cost basis CSV:

```bash
portfolio-monitor cost-basis input/cost_basis.csv
```

Set broker-reported account totals for reconciliation:

```bash
portfolio-monitor account-value "Fidelity" 100000 --as-of 2026-07-05
portfolio-monitor account-value "Robinhood" 25000 --as-of 2026-07-05
```

Generate the daily report:

```bash
portfolio-monitor analyze --daily
```

Assistant-friendly summary:

```bash
portfolio-monitor report --json
```

## Daily Monitoring

```bash
portfolio-monitor refresh-prices
portfolio-monitor analyze --daily
portfolio-monitor report --json
```

Review:

```text
reports/latest.html
```

## Monthly Decision Support

```bash
portfolio-monitor analyze --monthly
portfolio-monitor report --json
```

Monthly review should focus on allocation drift, concentration, missing cost basis, account reconciliation gaps, tax-review reminders, dividend estimates, and hold/watch/trim candidates. This is decision support only, not trade instruction.

## Assistant Usage

Expected assistant behavior:

- run commands locally
- keep private files local
- use `reports/latest.ai.json` for analysis
- use `reports/latest.html` for human-readable report references
- ask for missing account totals or cost basis when needed
- avoid raw statement injection unless troubleshooting
- never commit `input/`, `reports/`, `data/*.db`, `.env`, statements, exports, screenshots, or secrets

Recommended daily prompt:

```text
Run the daily portfolio monitoring loop.
Refresh prices, generate the daily report, read reports/latest.ai.json, and summarize:
- portfolio value
- daily change
- account reconciliation
- data-quality status
- risk alerts
- largest positions
- notable gain/loss changes
Do not read raw statements unless the report says REVIEW_REQUIRED or I ask you to debug ingestion.
```

## Reports

Daily analysis writes:

| File | Purpose |
|---|---|
| `reports/latest.html` | Human-readable interactive report |
| `reports/latest.ai.json` | Low-token structured context for assistant analysis |
| `reports/latest.compact.txt` | Compact text summary |
| `reports/latest.md` | Full Markdown report |
| `reports/latest.manifest.json` | Report artifact routing metadata |

The HTML report supports:

- search in Holdings Detail and Risk By Holding
- clickable column sorting
- multi-column show/hide controls
- account value reconciliation
- data-quality findings

## Docker

Build:

```bash
docker build -t portfolio-monitor:local .
```

Run with mounted local runtime directories:

```bash
docker compose run --rm portfolio-monitor ingest input
docker compose run --rm portfolio-monitor refresh-prices
docker compose run --rm portfolio-monitor analyze --daily
```

## Testing

```bash
pytest
python -m compileall portfolio_monitor tests
```

Or:

```bash
make test
make compile
```
