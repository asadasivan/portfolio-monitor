# Portfolio Monitor

Portfolio Monitor is a local-first portfolio monitoring tool intended to be operated from a terminal or with a local coding assistant such as Codex, Claude Code, or ChatGPT.

The repository contains code, documentation, and templates only. It does not include sample holdings, sample prices, brokerage statements, generated reports, or a demo portfolio. Each user starts with their own statements or normalized CSV files.

## Intended Workflow

1. Clone the repository.
2. Install the local tool.
3. Read this README directly, or provide it to your preferred assistant.
4. Provide your statements or normalized CSV files.
5. Import the files, refresh prices, generate the report, and review the output locally.

Input files can be provided in either of these ways:

- Place files under `input/` and run `portfolio-monitor ingest input`.
- Provide files directly to your assistant and ask it to use those files for ingestion. The assistant should keep the files local and avoid committing them.

Daily usage:

1. Refresh market prices.
2. Generate the daily report.
3. Review `reports/latest.html`.
4. Use `reports/latest.ai.json` for low-token assistant analysis.

The tool does deterministic parsing, storage, pricing, reconciliation, and report generation locally. Assistants should consume `reports/latest.ai.json` or `portfolio-monitor report --json`, not raw statements, unless parser debugging is required.

## What It Does

- Imports normalized holdings from CSV, Excel, or supported broker PDFs.
- Stores portfolio state in local SQLite.
- Updates prices from Yahoo Finance or a manual price CSV.
- Tracks account-level reconciliation against broker-reported totals.
- Calculates market value, gain/loss, allocation, dividend estimates, and concentration risk.
- Generates interactive local HTML reports.
- Generates low-token JSON and compact text reports for assistant review.
- Keeps statements, generated reports, local databases, and secrets out of Git by default.

## What It Does Not Do

- It does not execute trades.
- It does not log in to brokerage accounts.
- It does not scrape broker websites.
- It does not provide regulated financial, tax, or legal advice.
- It does not guarantee PDF parsing accuracy.
- It does not perform currency conversion yet.

## Setup

```bash
git clone https://github.com/YOUR_USERNAME/portfolio-monitor.git
cd portfolio-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,pdf,excel]"
cp config/sample.user.yaml config/user.yaml
```

## Add Your Data

Use your own statement files or normalized CSV files. The simplest option is to place them under `input/`.

```text
input/
  fidelity_statement.pdf
  robinhood_statement.pdf
  holdings.csv
  prices.csv
  cost_basis.csv
```

`input/` is ignored by Git. Do not commit real statements or exports.

If you are using an assistant, you can also provide the files directly in the assistant session and ask it to run ingestion against those local file paths. The same privacy rule applies: private files should stay local and should not be committed.

## First Run

Import statements or normalized CSV files:

```bash
portfolio-monitor ingest input
```

Refresh prices online:

```bash
portfolio-monitor refresh-prices
```

If you prefer manual prices, use:

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

Open:

```text
reports/latest.html
```

Assistant-friendly summary:

```bash
portfolio-monitor report --json
```

## Assistant Daily Monitoring Loop

Recommended prompt after setup:

```text
Read README.md.
Run the daily portfolio monitoring loop:
1. refresh prices,
2. generate the daily report,
3. review reports/latest.ai.json,
4. summarize performance, reconciliation, data-quality findings, and risks.
Do not read raw statements unless report quality is REVIEW_REQUIRED or I ask you to debug an import.
```

Daily commands:

```bash
portfolio-monitor refresh-prices
portfolio-monitor analyze --daily
portfolio-monitor report --json
```

Expected assistant behavior:

- run commands locally
- keep private files local
- use `reports/latest.ai.json` for analysis
- use `reports/latest.html` for human-readable report references
- ask for missing account totals or cost basis when needed
- avoid raw statement injection unless troubleshooting
- never commit `input/`, `reports/`, `data/*.db`, `.env`, statements, exports, screenshots, or secrets

Monthly decision-support commands:

```bash
portfolio-monitor analyze --monthly
portfolio-monitor report --json
```

## Input CSV Format

The statement or CSV must contain enough information to establish current holdings.

Required columns:

```csv
account,broker,market,symbol,name,asset_type,quantity,cost_basis,current_price,currency,sector,statement_date
```

Optional column:

```csv
annual_dividend_per_share
```

Example row format:

```csv
account,broker,market,symbol,name,asset_type,quantity,cost_basis,current_price,currency,sector,statement_date,annual_dividend_per_share
Taxable Brokerage,ExampleBroker,US,VTI,Vanguard Total Stock Market ETF,ETF,100,22000,250,USD,Broad Market,2026-07-04,3.60
```

Cost basis update CSV:

```csv
broker,market,symbol,average_cost
ExampleBroker,US,AAPL,150.00
```

Use `average_cost` for per-share/per-unit average cost, or `cost_basis` for total position cost basis.

Manual price CSV:

```csv
symbol,market,current_price
VTI,US,251.25
AAPL,US,213.40
BTC,GLOBAL,67250
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

## Privacy Model

Private runtime files are ignored by Git:

- `input/`
- `reports/`
- `data/*.db`
- `data/*.sqlite`
- `.env`
- PDFs and Excel files

Before pushing publicly:

```bash
sh scripts/check_public_release.sh
git status --ignored
```

Do not commit real statements, generated reports, local databases, API keys, cost-basis exports, or screenshots containing account data.

## Project Structure

```text
portfolio_monitor/      application code
config/                 user configuration template
input/                  private local statement imports, ignored
reports/                generated local reports, ignored
scripts/                local helper scripts
tests/                  focused unit tests with generated fixtures
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

## Known Limitations

- PDF parsing is best effort and should be verified against the original statement.
- Yahoo Finance data may be delayed, unavailable, or inconsistent with broker quotes.
- Currency conversion is not implemented.
- Tax handling is decision support only, not tax filing.
- Dividend estimates use imported annual income values when available; they are not guaranteed forecasts.

## Disclaimer

Portfolio Monitor is educational decision-support software. It is not an investment adviser, broker, tax adviser, or legal adviser. Validate imported data, calculations, and recommendations before making financial decisions.
