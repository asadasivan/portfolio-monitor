# Portfolio Monitor

Portfolio Monitor is a local-first portfolio monitoring tool for personal investment tracking. It imports user-provided brokerage statements or normalized CSV files, refreshes market prices, stores portfolio state locally, and generates local HTML and assistant-friendly reports.

The project can be run directly from a terminal or with a local coding assistant such as Codex, Claude Code, or ChatGPT.

## What It Does

- Imports normalized holdings from CSV, Excel, or supported broker PDFs.
- Stores portfolio state in local SQLite.
- Updates prices from Yahoo Finance or a manual price CSV.
- Tracks account-level reconciliation against broker-reported totals.
- Calculates market value, gain/loss, allocation, dividend estimates, and concentration risk.
- Generates interactive local HTML reports and compact assistant-ready summaries.

## What It Does Not Do

- It does not execute trades.
- It does not log in to brokerage accounts.
- It does not scrape broker websites.
- It does not provide regulated financial, tax, or legal advice.
- It does not perform currency conversion yet.

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/portfolio-monitor.git
cd portfolio-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,pdf,excel]"
cp config/sample.user.yaml config/user.yaml
```

After installation, follow the [Usage Guide](docs/USAGE.md) to add statements, run daily monitoring, generate reports, or operate the tool with an assistant.

## Documentation

- [Usage Guide](docs/USAGE.md): daily/monthly workflow, assistant monitoring loop, reports, Docker, and testing.
- [Input Formats](docs/INPUT_FORMATS.md): holdings CSV, manual prices, cost basis, and account reconciliation inputs.
- [Security](SECURITY.md): privacy model, local data handling, and what must not be committed.

## Project Structure

```text
portfolio_monitor/      application code
config/                 user configuration template
docs/                   usage and input format documentation
input/                  private local statement imports, ignored
reports/                generated local reports, ignored
scripts/                local helper scripts
tests/                  focused unit tests with generated fixtures
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
