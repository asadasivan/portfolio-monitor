#!/usr/bin/env sh
set -eu

if [ ! -d "input" ] || ! find input -maxdepth 1 -type f \( -name "*.csv" -o -name "*.xlsx" -o -name "*.xls" -o -name "*.pdf" \) | grep -q .; then
  printf 'No input files found. Add real brokerage statements or normalized holdings CSV files under input/.\n' >&2
  exit 1
fi

if [ ! -f "config/user.yaml" ]; then
  cp config/default.yaml config/user.yaml
fi

mkdir -p data reports

if [ -x ".venv/bin/portfolio-monitor" ]; then
  PORTFOLIO_MONITOR=".venv/bin/portfolio-monitor"
else
  PORTFOLIO_MONITOR="portfolio-monitor"
fi

"$PORTFOLIO_MONITOR" ingest input
"$PORTFOLIO_MONITOR" refresh-prices
"$PORTFOLIO_MONITOR" analyze --daily
"$PORTFOLIO_MONITOR" report --json
printf '\nHTML report: reports/latest.html\n'
