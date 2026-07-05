#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -m portfolio_monitor.cli refresh-prices
"$PYTHON_BIN" -m portfolio_monitor.cli analyze --daily
