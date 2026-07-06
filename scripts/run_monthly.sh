#!/usr/bin/env sh
set -eu

if [ -x ".venv/bin/portfolio-monitor" ]; then
  PORTFOLIO_MONITOR=".venv/bin/portfolio-monitor"
else
  PORTFOLIO_MONITOR="portfolio-monitor"
fi

"$PORTFOLIO_MONITOR" analyze --monthly
"$PORTFOLIO_MONITOR" report --json
printf '\nHTML report: reports/latest.html\n'
