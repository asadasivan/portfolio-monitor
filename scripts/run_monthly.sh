#!/usr/bin/env sh
set -eu

run_portfolio_monitor() {
  if command -v uv >/dev/null 2>&1; then
    uv run portfolio-monitor "$@"
  elif [ -x ".venv/bin/portfolio-monitor" ]; then
    .venv/bin/portfolio-monitor "$@"
  else
    portfolio-monitor "$@"
  fi
}

run_portfolio_monitor analyze --monthly
run_portfolio_monitor report --json
printf '\nHTML report: reports/latest.html\n'
