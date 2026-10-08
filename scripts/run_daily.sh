#!/usr/bin/env sh
set -eu

if [ ! -f "config/user.yaml" ]; then
  cp config/default.yaml config/user.yaml
fi

mkdir -p data reports

run_portfolio_monitor() {
  if command -v uv >/dev/null 2>&1; then
    uv run portfolio-monitor "$@"
  elif [ -x ".venv/bin/portfolio-monitor" ]; then
    .venv/bin/portfolio-monitor "$@"
  else
    portfolio-monitor "$@"
  fi
}

run_portfolio_monitor daily-loop input
