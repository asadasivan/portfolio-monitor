# Portfolio Monitor

Portfolio Monitor is a local-first portfolio tracking and performance analysis tool designed to be run by an AI coding assistant against user-provided brokerage statements or normalized CSV files. It refreshes market prices, stores portfolio state locally, and generates an interactive local HTML report.

The primary workflow is: create a local project in your AI assistant, place your real portfolio exports under `input/`, ask the assistant to run the monitoring loop, then review `reports/latest.html` to understand holdings, allocation, performance, data quality, dividends, and risk signals.

## What It Does

- Imports normalized holdings from CSV, Excel, or supported broker PDFs.
- Stores portfolio state in local SQLite.
- Updates prices from Yahoo Finance or a manual price CSV.
- Tracks account-level reconciliation against broker-reported totals.
- Calculates market value, gain/loss, allocation, dividend estimates, and concentration risk.
- Helps analyze investment performance using your own local files.
- Generates an interactive local HTML report with sorting, searching, and filtering, plus assistant-ready JSON context.

## What It Does Not Do

- It does not execute trades.
- It does not log in to brokerage accounts.
- It does not scrape broker websites.
- It supports portfolio tracking and performance analysis, but it does not provide investment, tax, legal, or trading advice.
- It does not guarantee live market or FX data availability; configured/manual values remain the fallback.

## Start Here

Use the [AI Assistant Usage Guide](docs/USAGE.md). It contains the setup command, the assistant prompt, and the expected output.

## Documentation

- [AI Assistant Usage Guide](docs/USAGE.md): primary AI assistant workflow.
- [Input Formats](docs/INPUT_FORMATS.md): holdings CSV, manual prices, cost basis, and account reconciliation inputs.
- [Reports](docs/REPORTS.md): report files, checks, output currency, FX refresh, and interpretation.
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

## Reports

See [Reports](docs/REPORTS.md) for generated files, report checks, holdings tables, output-currency settings, live FX refresh behavior, and interpretation guidance.

## Add Cost Basis

Cost basis is required for reliable gain/loss analysis. See [Cost Basis CSV](docs/INPUT_FORMATS.md#cost-basis-csv) for the accepted columns and import command.

## Add Broker Totals

Broker totals let the report reconcile parsed holdings against account values shown by the broker. See [Account Reconciliation](docs/INPUT_FORMATS.md#account-reconciliation) for the command format.

## Public Repository Safety

Before pushing publicly, run:

```bash
sh scripts/check_public_release.sh
git status --ignored
```

See [Security](SECURITY.md) for the canonical list of sensitive files that must stay out of Git.

## Known Limitations

- Yahoo Finance data may be delayed, unavailable, or inconsistent with broker quotes.
- Foreign exchange rates are fetched from Yahoo during the daily loop when possible, but configured rates remain the fallback.
- Gain/loss and tax-related fields are tracking inputs only, not tax filing guidance.
- Dividend estimates use imported annual income values when available; they are not guaranteed forecasts.

## Disclaimer

Portfolio Monitor is a local portfolio tracking and decision-support tool. It helps you review holdings, performance, allocation, data quality, dividends, and risk signals using your own files. It does not provide investment, tax, legal, or trading advice. Validate imported data and calculations before making financial or tax decisions.
