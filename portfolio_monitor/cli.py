from __future__ import annotations

import argparse
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from portfolio_monitor.analysis import build_daily_report, build_monthly_report
from portfolio_monitor.config import database_path, load_config, report_dir
from portfolio_monitor.importers import load_holdings
from portfolio_monitor.importers.pdf_importer import load_pdf_income_summaries
from portfolio_monitor.markets import fetch_current_prices
from portfolio_monitor.reports import write_compact_report, write_html_report, write_markdown_report
from portfolio_monitor.storage import PortfolioStore

SUPPORTED_STATEMENT_SUFFIXES = {".csv", ".xlsx", ".xls", ".pdf"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="portfolio-monitor")
    parser.add_argument("--config", default=None, help="Path to user config YAML")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Import a CSV, Excel, or PDF statement")
    import_parser.add_argument("path")
    import_parser.add_argument("--source", default="statement")

    ingest_parser = subparsers.add_parser("ingest", help="Import all supported statement files from a directory")
    ingest_parser.add_argument("path", nargs="?", default="input")
    ingest_parser.add_argument("--source", default="statement")

    prices_parser = subparsers.add_parser("prices", help="Update current prices from a CSV")
    prices_parser.add_argument("path")

    cost_basis_parser = subparsers.add_parser("cost-basis", help="Update cost basis from a CSV")
    cost_basis_parser.add_argument("path")

    account_value_parser = subparsers.add_parser("account-value", help="Set broker-reported account value")
    account_value_parser.add_argument("account")
    account_value_parser.add_argument("value")
    account_value_parser.add_argument("--as-of", default=None)
    account_value_parser.add_argument("--currency", default="USD")

    refresh_parser = subparsers.add_parser("refresh-prices", help="Fetch current prices online")
    refresh_parser.add_argument("--provider", default=None, help="Online price provider, for example yahoo")
    refresh_parser.add_argument("--timeout", type=int, default=6, help="Seconds to wait per symbol")

    subparsers.add_parser("holdings", help="List portfolio holdings")

    analyze_parser = subparsers.add_parser("analyze", help="Generate a daily or monthly report")
    period = analyze_parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--daily", action="store_true")
    period.add_argument("--monthly", action="store_true")

    report_parser = subparsers.add_parser("report", help="Print the latest generated report")
    report_parser.add_argument(
        "--full",
        action="store_true",
        help="Print the full Markdown report instead of the compact summary",
    )
    report_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the low-token structured AI context",
    )
    report_parser.add_argument(
        "--manifest",
        action="store_true",
        help="Print the assistant artifact manifest",
    )

    args = parser.parse_args()
    config = load_config(args.config)
    store = PortfolioStore(database_path(config))
    store.initialize()

    try:
        if args.command == "import":
            _import_statement(store, Path(args.path), args.source)
        elif args.command == "ingest":
            _ingest_directory(store, Path(args.path), args.source)
        elif args.command == "prices":
            _update_prices(store, Path(args.path))
        elif args.command == "cost-basis":
            _update_cost_basis(store, Path(args.path))
        elif args.command == "account-value":
            _set_account_value(store, args.account, args.value, args.as_of, args.currency)
        elif args.command == "refresh-prices":
            _refresh_prices(store, config, args.provider, args.timeout)
        elif args.command == "holdings":
            _print_holdings(store)
        elif args.command == "analyze":
            _analyze(store, config, daily=args.daily)
        elif args.command == "report":
            _print_latest_report(report_dir(config), full=args.full, json_output=args.json, manifest=args.manifest)
    finally:
        store.close()


def _import_statement(store: PortfolioStore, path: Path, source: str) -> None:
    holdings = load_holdings(path)
    counts = store.upsert_holdings(holdings, source=source)
    income_count = 0
    if path.suffix.lower() == ".pdf":
        income_count = store.upsert_income_summaries(load_pdf_income_summaries(path))
    print(
        f"Imported {len(holdings)} holdings from {path}. "
        f"Updated={counts['inserted_or_updated']}, "
        f"marked_missing={counts['marked_missing']}, "
        f"income_summaries={income_count}."
    )


def _ingest_directory(store: PortfolioStore, path: Path, source: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Statement input directory does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Expected a directory: {path}")

    files = sorted(
        file_path
        for file_path in path.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_STATEMENT_SUFFIXES
    )
    if not files:
        print(f"No supported statement files found in {path}. Supported: {sorted(SUPPORTED_STATEMENT_SUFFIXES)}")
        return

    imported = 0
    failed: list[tuple[Path, str]] = []
    for file_path in files:
        try:
            file_source = source if source != "statement" else file_path.stem
            _import_statement(store, file_path, file_source)
            imported += 1
        except Exception as exc:  # noqa: BLE001 - batch ingest should report all failures.
            failed.append((file_path, str(exc)))

    print(f"Ingest complete. files_imported={imported}, files_failed={len(failed)}.")
    for file_path, error in failed:
        print(f"  failed: {file_path} - {error}")


def _print_holdings(store: PortfolioStore) -> None:
    rows = store.all_holdings_rows()
    if not rows:
        print("No holdings imported yet.")
        return
    for row in rows:
        print(
            f"{row['status']:<28} {row['account']:<12} {row['market']:<6} "
            f"{row['symbol']:<14} qty={row['quantity']} price={row['current_price'] or 'n/a'}"
        )


def _update_prices(store: PortfolioStore, path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if "symbol" not in row or "current_price" not in row:
            raise ValueError("Price CSV must include symbol and current_price columns")
    counts = store.update_prices(rows)
    print(f"Updated prices for {counts['updated']} holdings; not_found={counts['not_found']}.")


def _update_cost_basis(store: PortfolioStore, path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if "symbol" not in row:
            raise ValueError("Cost basis CSV must include a symbol column")
        if "cost_basis" not in row and "average_cost" not in row:
            raise ValueError("Cost basis CSV must include cost_basis or average_cost")
    counts = store.update_cost_basis(rows)
    print(
        f"Updated cost basis for {counts['updated']} holdings; "
        f"not_found={counts['not_found']}, skipped={counts['skipped']}."
    )


def _set_account_value(store: PortfolioStore, account: str, value: str, as_of: str | None, currency: str) -> None:
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    store.upsert_account_value(account, Decimal(value.replace(",", "")), as_of_date, currency)
    print(f"Set account value: {account}={value} {currency} as_of={as_of_date.isoformat()}")


def _refresh_prices(store: PortfolioStore, config: dict, provider: str | None, timeout: int) -> None:
    holdings = store.active_holdings()
    if not holdings:
        print("No active holdings found. Import a statement first.")
        return
    provider_name = provider or config.get("market_data", {}).get("provider", "yahoo")
    results = fetch_current_prices(holdings, f"{provider_name}:{timeout}")
    price_rows = [
        {"symbol": result.symbol, "market": result.market, "current_price": str(result.current_price)}
        for result in results
        if result.status == "ok" and result.current_price is not None
    ]
    counts = store.update_prices(price_rows)
    failures = [result for result in results if result.status != "ok"]
    print(
        f"Fetched prices with {provider_name}. "
        f"Updated={counts['updated']}, failed={len(failures)}."
    )
    for failure in failures:
        print(
            f"  {failure.symbol} ({failure.provider_symbol}): "
            f"{failure.status} - {failure.message or 'no detail'}"
        )


def _analyze(store: PortfolioStore, config: dict, daily: bool) -> None:
    holdings = store.active_holdings()
    if not holdings:
        print("No active holdings found. Import a statement first.")
        return

    previous = store.latest_snapshot()
    previous_total = Decimal(previous["total_value"]) if previous else None
    if daily:
        report = build_daily_report(
            holdings,
            previous_total,
            config,
            store.latest_account_values(),
            store.latest_income_summaries(),
        )
        store.save_snapshot(date.fromisoformat(report["as_of"]), report["portfolio_value"])
    else:
        report = build_monthly_report(
            holdings,
            config,
            store.latest_account_values(),
            store.latest_income_summaries(),
        )

    markdown_path = write_markdown_report(report, report_dir(config))
    html_path = write_html_report(report, report_dir(config))
    compact_path = write_compact_report(report, report_dir(config))
    print(f"Wrote {report['report_type']} report: {markdown_path}")
    print(f"Wrote {report['report_type']} HTML report: {html_path}")
    print(f"Wrote {report['report_type']} compact report: {compact_path}")


def _print_latest_report(
    base_report_dir: Path,
    full: bool = False,
    json_output: bool = False,
    manifest: bool = False,
) -> None:
    selected_modes = [full, json_output, manifest]
    if sum(1 for mode in selected_modes if mode) > 1:
        raise ValueError("Choose only one report output mode: --full, --json, or --manifest.")
    if manifest:
        latest = base_report_dir / "latest.manifest.json"
    elif json_output:
        latest = base_report_dir / "latest.ai.json"
    elif full:
        latest = base_report_dir / "latest.md"
    else:
        latest = base_report_dir / "latest.compact.txt"
    if not latest.exists():
        print("No report generated yet.")
        return
    print(latest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
