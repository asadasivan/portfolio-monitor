#!/usr/bin/env sh
set -eu

failures=0

check_ignored() {
  path="$1"
  if [ -e "$path" ]; then
    if git check-ignore -q "$path"; then
      printf 'OK ignored: %s\n' "$path"
    else
      printf 'ERROR not ignored: %s\n' "$path"
      failures=$((failures + 1))
    fi
  fi
}

check_ignored "data/portfolio.db"
check_ignored "input/robinhood_cost_basis_2026-07-05.csv"
check_ignored "reports/latest.html"

if find input reports data -type f \( -name "*.pdf" -o -name "*.xlsx" -o -name "*.xls" \) | grep -q .; then
  printf 'WARNING private document-like files exist locally. They should remain ignored and untracked.\n'
fi

if [ "$failures" -ne 0 ]; then
  printf 'Public release check failed.\n'
  exit 1
fi

printf 'Public release check passed.\n'
