# Input Formats

The statement or CSV must contain enough information to establish current holdings for local portfolio tracking and performance analysis.

## Holdings CSV

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

Supported user-facing asset type labels are `Stock`, `ETF`, `Crypto`, `MF`, and `Cash`. The report normalizes these labels for display even when broker imports use longer source terms.

## Cost Basis CSV

Cost basis is required for reliable gain/loss analysis. If the report shows missing cost basis, export cost basis or tax-lot data from the broker and create a CSV under `input/`.

Use either average cost per share/unit:

```csv
broker,market,symbol,average_cost
ExampleBroker,US,AAPL,127.26
ExampleBroker,GLOBAL,BTC,43907.14
```

Or total position cost basis:

```csv
broker,market,symbol,cost_basis
ExampleBroker,US,AAPL,1275.02
ExampleBroker,GLOBAL,BTC,4573.03
```

If multiple accounts hold the same symbol, include `broker` and `market` exactly as shown in the holdings output so the update applies to the intended position.

Import command:

```bash
. .venv/bin/activate
portfolio-monitor cost-basis input/cost_basis.csv
portfolio-monitor analyze --daily
```

## Manual Price CSV

```csv
symbol,market,current_price
VTI,US,251.25
AAPL,US,213.40
BTC,GLOBAL,67250
```

Import command:

```bash
portfolio-monitor prices input/prices.csv
```

## Indian MF PDFs

Indian MF PDFs are supported when the importer can detect valuation pages with this schema:

- `Scheme / Scrip`: MF scheme name
- `Balance Units`: units held
- `Purchase Cost`: total cost basis
- `Market Value`: statement market value

For Sift Capital PDFs, the importer treats these rows as Indian MF holdings:

- `account`: `Indian Mutual Funds`
- `broker`: `Sift Capital`
- `market`: `IN`
- `asset_type`: `MF`
- `currency`: `INR`

When the online provider is `yahoo`, Indian MF holdings are refreshed from AMFI NAV data instead of Yahoo Finance. The statement market value is used only to seed the initial per-unit NAV and to help match the correct AMFI scheme.

Reports convert INR holdings into the configured `base_currency` for totals, allocation percentages, reconciliation, and risk calculations. HTML holding rows also show the original INR value in brackets, for example `120.00 (INR 10,000.00)`. Configure conversion rates in `currency_conversion.rates_to_base`.

## Account Reconciliation

Use broker-reported account totals to compare the tool's calculated value against the brokerage app or statement. This does not change holdings; it only adds a control check.

```bash
. .venv/bin/activate
portfolio-monitor account-value "Brokerage Account" 100000 --as-of 2026-07-06
portfolio-monitor account-value "Trading Account" 25000 --as-of 2026-07-06
portfolio-monitor analyze --daily
```
