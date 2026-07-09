#!/usr/bin/env sh
set -eu

if [ ! -f "config/user.yaml" ]; then
  cp config/default.yaml config/user.yaml
fi

mkdir -p data reports

if [ -x ".venv/bin/portfolio-monitor" ]; then
  PORTFOLIO_MONITOR=".venv/bin/portfolio-monitor"
else
  PORTFOLIO_MONITOR="portfolio-monitor"
fi

"$PORTFOLIO_MONITOR" daily-loop input
