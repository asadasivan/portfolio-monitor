from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.analysis import build_daily_report, build_monthly_report
from app.settings import database_path, load_config, report_dir
from app.ingestion import load_holdings
from app.ingestion.pdf_importer import load_pdf_income_summaries
from app.market_data import fetch_current_prices
from app.market_data.online import SUPPORTED_FX_CURRENCIES, fetch_fx_rates
from app.reporting import write_compact_report, write_html_report, write_markdown_report
from app.persistence import PortfolioStore

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
    ingest_parser.add_argument("--new-only", action="store_true", help="Import only files not previously imported")

    daily_loop_parser = subparsers.add_parser("daily-loop", help="Run the daily workflow with incremental ingestion")
    daily_loop_parser.add_argument("path", nargs="?", default="input")
    daily_loop_parser.add_argument("--provider", default=None, help="Online price provider, for example yahoo")
    daily_loop_parser.add_argument("--timeout", type=int, default=6, help="Seconds to wait per symbol")

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

    fx_parser = subparsers.add_parser("refresh-fx", help="Fetch live FX rates for configured report currencies")
    fx_parser.add_argument("--provider", default=None, help="Online FX provider, for example yahoo")
    fx_parser.add_argument("--timeout", type=int, default=6, help="Seconds to wait per currency pair")

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
            _ingest_directory(store, Path(args.path), args.source, new_only=args.new_only)
        elif args.command == "daily-loop":
            _daily_loop(store, config, Path(args.path), args.provider, args.timeout)
        elif args.command == "prices":
            _update_prices(store, Path(args.path))
        elif args.command == "cost-basis":
            _update_cost_basis(store, Path(args.path))
        elif args.command == "account-value":
            _set_account_value(store, args.account, args.value, args.as_of, args.currency)
        elif args.command == "refresh-prices":
            _refresh_prices(store, config, args.provider, args.timeout)
        elif args.command == "refresh-fx":
            _refresh_fx_rates(config, args.provider, args.timeout, store=store)
        elif args.command == "holdings":
            _print_holdings(store)
        elif args.command == "analyze":
            _analyze(store, config, daily=args.daily)
        elif args.command == "report":
            _print_latest_report(report_dir(config), full=args.full, json_output=args.json, manifest=args.manifest)
    finally:
        store.close()


def _import_statement(store: PortfolioStore, path: Path, source: str) -> dict[str, object]:
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
    return {
        "holdings_count": len(holdings),
        "accounts": {_holding_account_label(holding) for holding in holdings},
        "account_statement_dates": _account_statement_dates(holdings),
    }


def _ingest_directory(store: PortfolioStore, path: Path, source: str, new_only: bool = False) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Statement input directory does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Expected a directory: {path}")

    files = _statement_files(path)
    if not files:
        print(f"No supported statement files found in {path}. Supported: {sorted(SUPPORTED_STATEMENT_SUFFIXES)}")
        return {"imported": 0, "failed": 0, "skipped_seen": 0, "imported_accounts": set(), "account_statement_dates": {}}

    imported = 0
    skipped_seen = 0
    imported_accounts: set[str] = set()
    account_statement_dates: dict[str, set[date]] = {}
    failed: list[tuple[Path, str]] = []
    imported_sources = store.imported_sources() if new_only else set()
    imported_digests = store.imported_file_digests() if new_only else set()
    for file_path in files:
        try:
            file_source = source if source != "statement" else file_path.stem
            digest = _file_digest(file_path)
            if new_only and (digest in imported_digests or file_source in imported_sources):
                skipped_seen += 1
                continue
            import_result = _import_statement(store, file_path, file_source)
            holdings_count = int(import_result["holdings_count"])
            imported_accounts.update(str(account) for account in import_result["accounts"])
            _merge_account_statement_dates(account_statement_dates, import_result["account_statement_dates"])
            store.record_imported_file(file_path, file_source, digest, holdings_count)
            imported_sources.add(file_source)
            imported_digests.add(digest)
            imported += 1
        except Exception as exc:  # noqa: BLE001 - batch ingest should report all failures.
            failed.append((file_path, str(exc)))

    print(f"Ingest complete. files_imported={imported}, files_skipped_seen={skipped_seen}, files_failed={len(failed)}.")
    for file_path, error in failed:
        print(f"  failed: {file_path} - {error}")
    return {
        "imported": imported,
        "failed": len(failed),
        "skipped_seen": skipped_seen,
        "imported_accounts": imported_accounts,
        "account_statement_dates": account_statement_dates,
    }


def _daily_loop(store: PortfolioStore, config: dict, input_path: Path, provider: str | None, timeout: int) -> None:
    holdings = store.active_holdings()
    input_files = _statement_files(input_path) if input_path.exists() and input_path.is_dir() else []
    if not holdings and not input_files:
        raise SystemExit(
            "No active portfolio and no supported input files found. "
            "Add real brokerage statements or a normalized holdings CSV under input/."
        )

    if input_files:
        ingest_result = _ingest_directory(store, input_path, source="statement", new_only=True)
    else:
        print(f"No supported statement files found in {input_path}; using active portfolio database.")
        ingest_result = {"imported": 0, "imported_accounts": set(), "account_statement_dates": {}}

    if not store.active_holdings():
        raise SystemExit("No active holdings found after ingestion. Add brokerage statements or a normalized holdings CSV.")

    failed_prices = _refresh_prices(store, config, provider, timeout)
    if failed_prices:
        print("Some online price refreshes failed. Provide a manual price CSV for the failed symbols if needed.")
    failed_fx = _refresh_fx_rates(config, provider, timeout, store=store)
    if failed_fx:
        print("Some live FX refreshes failed. Existing configured FX rates were kept for failed currencies.")
    report_date = date.today()
    account_values = store.latest_account_values()
    current_value_accounts = _current_value_accounts(account_values, report_date)
    active_account_statement_dates = _account_statement_dates(store.active_holdings())
    broker_total_requests = _broker_total_requests(
        active_account_statement_dates,
        current_value_accounts,
        report_date,
    ) if ingest_result["imported"] else []
    _analyze(
        store,
        config,
        daily=True,
        force_account_reconciliation=bool(current_value_accounts),
        reconciliation_accounts=None,
        broker_total_requests=broker_total_requests,
        broker_check_mode="statement_import" if ingest_result["imported"] else "broker_totals",
    )
    _print_daily_loop_outputs(report_dir(config))


def _statement_files(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return sorted(
        file_path
        for file_path in path.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_STATEMENT_SUFFIXES
    )


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _holding_account_label(holding) -> str:
    return holding.broker if holding.broker else holding.account


def _account_statement_dates(holdings) -> dict[str, set[date]]:
    result: dict[str, set[date]] = {}
    for holding in holdings:
        result.setdefault(_holding_account_label(holding), set()).add(holding.statement_date)
    return result


def _merge_account_statement_dates(target: dict[str, set[date]], source) -> None:
    for account, statement_dates in source.items():
        target.setdefault(str(account), set()).update(statement_dates)


def _account_value_as_of(value) -> date | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("as_of")
    if not raw:
        return None
    return raw if isinstance(raw, date) else date.fromisoformat(str(raw))


def _current_value_accounts(account_values: dict, report_date: date) -> set[str]:
    return {
        account
        for account, value in account_values.items()
        if _account_value_as_of(value) == report_date
    }


def _broker_total_requests(account_statement_dates, current_value_accounts: set[str], report_date: date) -> list[dict[str, str]]:
    requests = []
    for account, statement_dates in sorted(account_statement_dates.items()):
        if account in current_value_accounts:
            continue
        latest_statement_date = max(statement_dates)
        reason = "missing_current_broker_total"
        if latest_statement_date != report_date:
            reason = "statement_not_current_day"
        requests.append(
            {
                "account": str(account),
                "statement_as_of": latest_statement_date.isoformat(),
                "required_as_of": report_date.isoformat(),
                "reason": reason,
            }
        )
    return requests


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


def _print_daily_loop_outputs(base_report_dir: Path) -> None:
    print(f"HTML report: {base_report_dir / 'latest.html'}")
    print(f"Assistant context: {base_report_dir / 'latest.ai.json'}")
    print(f"Compact summary: {base_report_dir / 'latest.compact.txt'}")


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


def _base_currency(config: dict) -> str:
    return str(config.get("base_currency", "USD")).upper()


def _configured_fx_currencies(config: dict) -> set[str]:
    return set(_configured_rates_to_base(config))


def _configured_rates_to_base(config: dict) -> dict[str, Decimal]:
    conversion = config.get("currency_conversion", {})
    rates = conversion.get("rates_to_base", {}) if isinstance(conversion, dict) else {}
    if not isinstance(rates, dict) and isinstance(conversion, dict):
        rates = {
            currency: rate
            for currency, rate in conversion.items()
            if str(currency).upper() == str(currency) and currency != "rates_to_base"
        }
    if not isinstance(rates, dict):
        return {}
    return {str(currency).upper(): Decimal(str(rate)) for currency, rate in rates.items()}


def _output_currency(config: dict) -> str | None:
    reporting = config.get("reporting", {})
    if isinstance(reporting, dict) and reporting.get("output_currency"):
        return str(reporting["output_currency"]).upper()
    return None


def _fx_currencies(config: dict, store: PortfolioStore | None = None) -> set[str]:
    currencies = _configured_fx_currencies(config)
    output_currency = _output_currency(config)
    if output_currency:
        currencies.add(output_currency)
    if store is not None:
        currencies.update(str(holding.currency).upper() for holding in store.active_holdings())
        currencies.update(str(value.get("currency", "")).upper() for value in store.latest_account_values().values() if isinstance(value, dict))
    return {currency for currency in currencies if currency}


def _refresh_fx_rates(config: dict, provider: str | None, timeout: int, store: PortfolioStore | None = None) -> int:
    base_currency = _base_currency(config)
    currencies = _fx_currencies(config, store) | {base_currency}
    provider_name = provider or config.get("market_data", {}).get("provider", "yahoo")
    results = fetch_fx_rates(base_currency, currencies, f"{provider_name}:{timeout}")
    conversion = config.setdefault("currency_conversion", {})
    if not isinstance(conversion, dict):
        conversion = {}
        config["currency_conversion"] = conversion
    rates = conversion.setdefault("rates_to_base", {})
    if not isinstance(rates, dict):
        rates = _configured_rates_to_base(config)
        conversion["rates_to_base"] = rates

    previous_rates = _configured_rates_to_base(config)
    updated = 0
    failures = []
    for result in results:
        if result.status == "ok" and result.rate_to_base is not None:
            rates[result.currency] = result.rate_to_base
            updated += 1
        else:
            failures.append(result)

    current_rates = {str(currency).upper(): Decimal(str(rate)) for currency, rate in rates.items()}
    changed_currencies = sorted(
        currency
        for currency, rate in current_rates.items()
        if previous_rates.get(currency) is not None and previous_rates[currency] != rate
    )
    config["_fx_refresh"] = {
        "provider": provider_name,
        "base_currency": base_currency,
        "previous_rates_to_base": previous_rates,
        "rates_to_base": current_rates,
        "updated": updated,
        "failed": len(failures),
        "changed_currencies": changed_currencies,
    }

    print(f"Fetched FX rates with {provider_name}. Updated={updated}, failed={len(failures)}.")
    for failure in failures:
        print(
            f"  {failure.currency}/{failure.base_currency} ({failure.provider_symbol}): "
            f"{failure.status} - {failure.message or 'no detail'}"
        )
    return len(failures)


def _snapshot_fx_rates(snapshot) -> dict[str, Decimal] | None:
    if not snapshot or "fx_rates_json" not in snapshot.keys() or not snapshot["fx_rates_json"]:
        return None
    raw = json.loads(snapshot["fx_rates_json"])
    if not isinstance(raw, dict):
        return None
    return {str(currency).upper(): Decimal(str(rate)) for currency, rate in raw.items()}


def _preserve_same_day_fx_rates(config: dict, snapshot) -> dict[str, Decimal] | None:
    current_rates = _snapshot_fx_rates(snapshot)
    if not current_rates:
        return None
    fallback_rates = _configured_rates_to_base(config)
    if not fallback_rates:
        return None
    conversion = config.setdefault("currency_conversion", {})
    if not isinstance(conversion, dict):
        conversion = {}
        config["currency_conversion"] = conversion
    conversion["rates_to_base"] = current_rates
    changed_currencies = sorted(
        currency
        for currency in set(fallback_rates) | set(current_rates)
        if fallback_rates.get(currency) is not None
        and current_rates.get(currency) is not None
        and fallback_rates[currency] != current_rates[currency]
    )
    config["_fx_refresh"] = {
        "provider": "saved_snapshot",
        "base_currency": _base_currency(config),
        "previous_rates_to_base": fallback_rates,
        "rates_to_base": current_rates,
        "updated": 0,
        "failed": 0,
        "changed_currencies": changed_currencies,
    }
    return fallback_rates


def _refresh_prices(store: PortfolioStore, config: dict, provider: str | None, timeout: int) -> int:
    holdings = store.active_holdings()
    if not holdings:
        print("No active holdings found. Import a statement first.")
        return 0
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
    return len(failures)


def _analyze(
    store: PortfolioStore,
    config: dict,
    daily: bool,
    force_account_reconciliation: bool = False,
    reconciliation_accounts: set[str] | None = None,
    broker_total_requests: list[dict[str, str]] | None = None,
    broker_check_mode: str | None = None,
) -> None:
    holdings = store.active_holdings()
    if not holdings:
        print("No active holdings found. Import a statement first.")
        return

    if daily:
        report_date = date.today()
        today_snapshot = store.latest_snapshot()
        fallback_rates = None
        if today_snapshot and today_snapshot["snapshot_date"] == report_date.isoformat() and "_fx_refresh" not in config:
            fallback_rates = _preserve_same_day_fx_rates(config, today_snapshot)
        previous = store.latest_snapshot_before(report_date)
        previous_total = Decimal(previous["total_value"]) if previous else None
        previous_rates = json.loads(previous["fx_rates_json"]) if previous and "fx_rates_json" in previous.keys() and previous["fx_rates_json"] else None
        if fallback_rates is not None:
            previous_rates = fallback_rates
        report = build_daily_report(
            holdings,
            previous_total,
            config,
            store.latest_account_values(),
            store.latest_income_summaries(),
            force_account_reconciliation=force_account_reconciliation,
            reconciliation_accounts=reconciliation_accounts,
            broker_total_requests=broker_total_requests,
            broker_check_mode=broker_check_mode,
            previous_rates_to_base=previous_rates,
        )
        store.save_snapshot(
            date.fromisoformat(report["as_of"]),
            report["portfolio_value"],
            report.get("currency_conversion", {}).get("rates_to_base", {}),
        )
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
