# Portfolio Monitor

Portfolio Monitor is a local-first portfolio monitoring tool designed to be run by an AI coding assistant against user-provided brokerage statements or normalized CSV files. It refreshes market prices, stores portfolio state locally, and generates an interactive local HTML report.

The primary workflow is: create a local project in your AI assistant, place your real portfolio exports under `input/`, ask the assistant to run the monitoring loop, then review `reports/latest.html`.

## Report Checks

The HTML report includes compact checks near the top:

- **Broker total check** compares the tool's parsed account value with the total value you see in the broker app or statement. If it says `NOT SET`, no broker-reported totals have been entered yet.
- **Data quality** summarizes import gaps. `Needs review` means the report found a data issue that may affect trust in the numbers. `Missing optional data` usually means gain/loss or tax-lot analysis is incomplete because cost basis is missing.
- **Price freshness** tells you whether values are based on stored/imported prices. Refresh prices or import a manual price CSV before relying on current day movement.

## Add Cost Basis

Cost basis is required for reliable gain/loss analysis. If the report shows missing cost basis, export cost basis or tax-lot data from the broker and create a CSV under `input/`.

Use either total position cost basis:

```csv
broker,market,symbol,cost_basis
Robinhood,US,AAPL,1275.02
Robinhood,GLOBAL,BTC,4573.03
```

Or average cost per share/unit:

```csv
broker,market,symbol,average_cost
Robinhood,US,AAPL,127.26
Robinhood,GLOBAL,BTC,43907.14
```

Then import it:

```bash
. .venv/bin/activate
portfolio-monitor cost-basis input/cost_basis.csv
portfolio-monitor analyze --daily
```

If multiple accounts hold the same symbol, include `broker` and `market` exactly as shown in the holdings output so the update applies to the intended position.

## Add Broker Totals

Broker totals let the report reconcile parsed holdings against the account value shown by the broker. Use the total account value from the broker app or statement and its as-of date:

```bash
. .venv/bin/activate
portfolio-monitor account-value "Fidelity" 1494398.79 --as-of 2026-07-06
portfolio-monitor account-value "Robinhood" 59891.52 --as-of 2026-07-06
portfolio-monitor analyze --daily
```

This does not change holdings. It only adds a control check so the report can show whether parsed positions approximately match broker-reported account totals.

## What It Does

- Imports normalized holdings from CSV, Excel, or supported broker PDFs.
- Stores portfolio state in local SQLite.
- Updates prices from Yahoo Finance or a manual price CSV.
- Tracks account-level reconciliation against broker-reported totals.
- Calculates market value, gain/loss, allocation, dividend estimates, and concentration risk.
- Generates an interactive local HTML report with sorting, searching, and filtering, plus assistant-ready JSON context.

## What It Does Not Do

- It does not execute trades.
- It does not log in to brokerage accounts.
- It does not scrape broker websites.
- It does not provide regulated financial, tax, or legal advice.
- It does not perform currency conversion yet.

## Start Here

Use the [AI Assistant Usage Guide](docs/USAGE.md). It contains the setup command, the assistant prompt, and the expected output.

## Documentation

- [AI Assistant Usage Guide](docs/USAGE.md): primary AI assistant workflow.
- [Input Formats](docs/INPUT_FORMATS.md): holdings CSV, manual prices, cost basis, and account reconciliation inputs.
- [Security](SECURITY.md): privacy model, local data handling, and what must not be committed.

## Project Structure

```text
src/app/                 application source
  domain/                portfolio domain objects
  ingestion/             CSV, Excel, and PDF input loading
  analysis/              portfolio calculations and risk signals
  market_data/           market price provider integration
  persistence/           local SQLite storage
  reporting/             HTML, Markdown, compact text, and AI JSON rendering
config/                  user configuration template; config/user.yaml is local and ignored
docs/                    usage and input format documentation
input/                   private local statement imports; contents ignored
data/                    local SQLite runtime data; contents ignored
reports/                 generated report output; contents ignored
scripts/                 assistant-friendly helper scripts
tests/                   focused unit tests
```

## Public Repository Safety

Before pushing publicly, run these checks to ensure real statements, generated reports, local databases, API keys, and other private portfolio files are not committed to GitHub:

```bash
sh scripts/check_public_release.sh
git status --ignored
```

Do not commit real statements, generated reports, local databases, API keys, cost-basis exports, price exports, holdings exports, or screenshots containing account data.

## Known Limitations

- Yahoo Finance data may be delayed, unavailable, or inconsistent with broker quotes.
- Currency conversion is not implemented.
- Tax handling is decision support only, not tax filing.
- Dividend estimates use imported annual income values when available; they are not guaranteed forecasts.

## Disclaimer

Portfolio Monitor is educational decision-support software. It is not an investment adviser, broker, tax adviser, or legal adviser. Validate imported data, calculations, and recommendations before making financial decisions.
