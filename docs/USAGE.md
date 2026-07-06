# AI Assistant Usage Guide

Use Portfolio Monitor through a local AI coding assistant. The assistant sets up the local project, runs the monitoring loop, and produces `reports/latest.html` as the main output.

## 1. Create the Project

In your AI assistant, create or open a local project/workspace. Then ask it to run setup:

```bash
git clone https://github.com/asadasivan/portfolio-monitor.git && cd portfolio-monitor && make setup
```

## 2. Add Your Files

Add your real brokerage statements or normalized holdings CSV files to `input/`.

Do not create or use demo, sample, synthetic, or test portfolio files for normal monitoring.

## 3. Ask the Assistant to Run the Loop

Use this prompt:

```text
Run the Portfolio Monitor daily loop using only my real files under input/.
If input/ is missing or empty, stop and ask me to add brokerage statements or a normalized holdings CSV.

Generate the interactive HTML report and summarize the result.
The main output should be reports/latest.html with sorting, searching, and filtering.
Use reports/latest.ai.json only as assistant context for the summary.
Run sh scripts/run_daily.sh for the daily loop.

Summarize:
- portfolio value
- daily change
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
Do not present the result as investment, tax, legal, or trading advice.
```

## Expected Output

The assistant should provide:

- `reports/latest.html`: the primary user-facing report, with sorting, searching, and filtering.
- A concise summary of portfolio value, reconciliation, data quality, risk alerts, largest positions, and notable gain/loss changes.
- Any follow-up files or values needed from you, such as manual prices, cost basis, or broker-reported totals.

## Guardrails

- Use only user-provided real input files.
- Keep `input/`, `data/`, and `reports/` local.
- Never commit statements, exports, screenshots, reports, databases, `.env`, or secrets.
