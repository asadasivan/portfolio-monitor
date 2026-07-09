# Reports

Portfolio Monitor writes human-readable and assistant-ready report artifacts under `reports/`.

## Generated Files

- `reports/latest.html`: primary user-facing interactive report with sorting, searching, and filtering.
- `reports/latest.ai.json`: compact structured context for AI assistant summaries.
- `reports/latest.compact.txt`: low-token plain-text summary.
- `reports/latest.md`: Markdown report.

Use `reports/latest.html` for human review. Use `reports/latest.ai.json` only as assistant context for summaries and repeated daily runs.

`reports/latest.ai.json` is intentionally bounded for token efficiency. Large detail lists such as quality issues, reconciliation rows, broker-total requests, stale totals, risk alerts, signals, and notes include the first relevant items plus `total_count` and `omitted_count` metadata when truncated. Use `reports/latest.html` for the full human-readable detail.

The daily loop prints artifact paths rather than dumping `reports/latest.ai.json` to stdout. This keeps routine assistant runs small while preserving the file for explicit summary context.

## Holdings Tables

The HTML report groups holdings into:

- US Stocks and ETF
- India MF and Stocks
- Crypto
- Other Holdings, when holdings do not fit the primary groups

Each holdings table includes a total row. Rows with negative gain/loss values are highlighted across the full row.

## Daily Change And FX Revaluation

When live FX rates change during a daily run, the report separates portfolio movement into three values:

- **Market Daily Change**: estimated portfolio movement after removing the effect of refreshed FX rates.
- **FX Revaluation**: change caused by revaluing non-base-currency holdings or broker totals with refreshed FX rates.
- **Total Change After FX**: total change versus the prior saved snapshot after applying refreshed FX rates.

This avoids presenting an FX-rate revaluation as if it were pure market performance. If FX rates do not change during the run, the report shows the normal **Daily Change** card.

## Report Checks

The HTML report includes compact checks near the top.

### Broker Total Check

Broker total check compares the tool's parsed account value with the total value you see in the broker app or statement.

- `MATCHED`: parsed value is within the configured tolerance.
- `WATCH` or `REVIEW`: parsed value differs enough to require review.
- `NEEDED`: a current broker/app total is needed before reconciliation can run.
- `SKIPPED`: broker totals are missing or older than the current-price report.

Broker reconciliation is date-aware:

- On normal price-only daily runs, older broker totals are skipped because live prices naturally drift from old statement/app values.
- When the daily loop imports a new statement file, the report asks for same-day broker/app totals for any active account that does not have one.
- If an imported statement is older than today, provide the current broker/app total by checking the brokerage account before relying on reconciliation.

Example:

```bash
portfolio-monitor account-value "Robinhood" 55645.07 --as-of 2026-07-09
portfolio-monitor account-value "Fidelity" 1479869.13 --as-of 2026-07-09
portfolio-monitor analyze --daily
```

Use the account label shown in the report, such as `Robinhood`, `Fidelity`, or `Sift Capital`.

### Data Quality

Data quality summarizes import gaps and calculation issues.

- `OK`: no detected data-quality issues.
- `WATCH`: review needed before relying on some values.
- `REVIEW_REQUIRED`: critical data issue that should be resolved before relying on the report.

Cost basis is required for reliable gain/loss analysis. If cost basis is missing, import a cost basis CSV before relying on gain/loss outputs.

### Price Freshness

Price freshness indicates whether values are based on stored/imported prices or refreshed online prices. If online price refresh fails, provide a manual price CSV for failed symbols before relying on current-day movement.

## Report Output Currency

Reports calculate totals, allocation percentages, reconciliation, and risk in the configured `base_currency`. Human-readable report output can use a separate display currency through `reporting.output_currency`.

Example:

```yaml
base_currency: USD
currency_conversion:
  rates_to_base:
    USD: 1
    INR: 0.012
reporting:
  output_currency: INR
```

With `output_currency: INR`, report headings use labels such as `Value (INR)` and `Market Value (INR)`. Displayed values are converted from `base_currency` using `currency_conversion.rates_to_base`. HTML holding rows still show original native values in brackets when the holding currency differs from the selected output currency.

Common display labels are supported for:

`USD`, `EUR`, `GBP`, `JPY`, `INR`, `CAD`, `AUD`, `CHF`, `CNY`, `HKD`, `SGD`, `NZD`, `SEK`, `NOK`, `KRW`, `AED`, `SAR`, `ZAR`, `BRL`, and `MXN`.

If the selected output currency has no configured or refreshed rate, the report falls back to `base_currency` to avoid showing misleading converted values.

## Live FX Refresh

During the daily loop, the tool tries to refresh live FX rates from Yahoo for:

- configured currencies in `currency_conversion.rates_to_base`
- holding currencies
- broker-total currencies
- the selected `reporting.output_currency`
- the configured `base_currency`

If live FX refresh fails for a currency, the report keeps the configured fallback rate.

You can refresh FX rates directly:

```bash
portfolio-monitor refresh-fx
```

## Disclaimer

Reports are local decision-support artifacts. They are not investment, tax, legal, or trading advice. Validate imported data, prices, cost basis, broker totals, and currency rates before using the report for financial decisions.
