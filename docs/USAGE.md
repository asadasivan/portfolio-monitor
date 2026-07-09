# AI Assistant Usage Guide

Use Portfolio Monitor through a local AI coding assistant. The assistant sets up the local project, runs the monitoring loop, and produces `reports/latest.html` so you can review portfolio value, performance, allocation, data quality, dividends, and risk signals.

## 1. Create the Project

In your AI assistant, create or open a local project/workspace. Then ask it to run setup:

```bash
git clone https://github.com/asadasivan/portfolio-monitor.git && cd portfolio-monitor && make setup
```

## 2. Add Your Files

For the first run, add your real brokerage statements or normalized holdings CSV files to `input/`.

Do not create or use demo, sample, synthetic, or test portfolio files for normal monitoring.

After the active portfolio database has been initialized, daily runs do not require the same statement files to be present. Add new files to `input/` only when you have a new statement or updated normalized holdings export to import.

## 3. Daily Loop Behavior

`sh scripts/run_daily.sh` runs the daily loop with this sequence:

1. If there is no active portfolio yet, it requires at least one supported real input file under `input/`.
2. If new supported files exist under `input/`, it imports only files that have not already been imported.
3. If there are no new files, it skips statement ingestion and uses the active portfolio database.
4. It refreshes US market prices through Yahoo Finance and Indian MF NAVs through AMFI-backed lookup.
5. It regenerates `reports/latest.html`, `reports/latest.ai.json`, and the compact text report.

The report uses three holdings tables:

- US Stocks and ETF
- India MF and Stocks
- Crypto

`reports/latest.html` is the full human report. `reports/latest.ai.json` is intentionally compact and should be used only as assistant context to keep repeated daily runs low-token.

## Broker Total Checks

Broker total checks are intentionally date-aware:

- On normal price-only daily runs, older broker totals are shown as skipped because live prices will naturally drift from old statement/app values.
- Broker reconciliation is an all-account check: every account with a same-day broker/app total is reconciled.
- When the daily loop imports a new statement file, the report asks for same-day broker/app totals for any active account that does not have one.
- If an imported statement is older than today, provide the current broker/app total by looking at the brokerage account before relying on reconciliation:

```bash
portfolio-monitor account-value "Robinhood" 55645.07 --as-of 2026-07-09
portfolio-monitor account-value "Fidelity" 1479869.13 --as-of 2026-07-09
```

Use the account label shown in the report, such as `Robinhood`, `Fidelity`, or `Sift Capital`.

## 4. Ask the Assistant to Run the Loop

Use this prompt:

```text
Run the Portfolio Monitor daily loop.
If there is no active portfolio database yet and input/ is missing or empty, stop and ask me to add brokerage statements or a normalized holdings CSV.
If the active portfolio already exists, import only new files from input/ if present; otherwise just refresh online prices and generate the report.

Generate the interactive HTML report and summarize the result.
The main output should be reports/latest.html with sorting, searching, and filtering.
Use reports/latest.ai.json only as assistant context for the summary.
Run sh scripts/run_daily.sh for the daily loop.

Summarize:
- portfolio value
- daily change
- overall performance
- account reconciliation
- data-quality status
- risk alerts
- largest positions
- notable gain/loss changes

If online price refresh fails, ask me for a manual price CSV.
If cost basis is missing, ask me for a cost basis CSV before relying on gain/loss analysis.
If account reconciliation is needed, ask me for broker-reported totals and the as-of date.

Do not read raw statements unless reports/latest.ai.json shows REVIEW_REQUIRED or I ask you to debug ingestion.
Do not create demo, sample, synthetic, or test portfolio files.
Do not recommend what to buy, sell, hold, rebalance, or use for tax filing.
```

## Expected Output

The assistant should provide:

- `reports/latest.html`: the primary user-facing report, with sorting, searching, and filtering.
- A concise summary of portfolio value, performance, reconciliation, data quality, risk alerts, largest positions, and notable gain/loss changes.
- Any follow-up files or values needed from you, such as manual prices, cost basis, or broker-reported totals.

## Guardrails

- Use only user-provided real input files.
- Keep private portfolio artifacts local. See [Security](../SECURITY.md) for what must not be committed.
