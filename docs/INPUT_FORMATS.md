# Input Formats

The statement or CSV must contain enough information to establish current holdings.

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

## Cost Basis CSV

```csv
broker,market,symbol,average_cost
ExampleBroker,US,AAPL,150.00
```

Use `average_cost` for per-share/per-unit average cost, or `cost_basis` for total position cost basis.

Import command:

```bash
portfolio-monitor cost-basis input/cost_basis.csv
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

## Account Reconciliation

Use broker-reported account totals to compare the tool's calculated value against the brokerage app or statement.

```bash
portfolio-monitor account-value "Fidelity" 100000 --as-of 2026-07-05
portfolio-monitor account-value "Robinhood" 25000 --as-of 2026-07-05
```
