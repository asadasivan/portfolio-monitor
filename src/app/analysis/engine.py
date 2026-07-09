from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.models import Holding, IncomeSummary, QualityIssue

AccountValue = Decimal | dict[str, Any]


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: str
    reason: str


def build_daily_report(
    holdings: list[Holding],
    previous_total: Decimal | None,
    config: dict[str, Any],
    account_values: dict[str, AccountValue] | None = None,
    income_summaries: list[IncomeSummary] | None = None,
    force_account_reconciliation: bool = False,
    reconciliation_accounts: set[str] | None = None,
    broker_total_requests: list[dict[str, Any]] | None = None,
    broker_check_mode: str | None = None,
) -> dict[str, Any]:
    report_date = date.today()
    applicable_account_values = _applicable_account_values(account_values, report_date)
    reconciliation_account_values = _reconciliation_account_values(
        account_values,
        applicable_account_values,
        force_account_reconciliation,
        reconciliation_accounts,
    )
    holdings_total = sum((_market_value(holding, config) for holding in holdings), Decimal("0"))
    holdings_by_account = _sum_by_account_name(holdings, config)
    stale_account_values = _stale_account_values(
        account_values,
        report_date,
        checked_accounts=set(reconciliation_account_values),
        account_labels=set(holdings_by_account),
    )
    by_account = _account_breakdown(holdings_by_account, applicable_account_values, config)
    total = sum(by_account.values(), Decimal("0")) if applicable_account_values else holdings_total
    by_asset_type = _sum_by_asset_type(holdings, config)
    concentration = _concentration_alerts(holdings, total, config)
    dividends = _dividend_summary(holdings, config)
    actual_income = _actual_income_summary(income_summaries or [])
    holding_rows = _holding_rows(holdings, total, config)
    reconciliation = _account_reconciliation(holdings_by_account, reconciliation_account_values, config)
    quality = _quality_summary(holdings, reconciliation)
    daily_change = None
    daily_change_pct = None
    if previous_total and previous_total > 0:
        daily_change = total - previous_total
        daily_change_pct = (daily_change / previous_total) * Decimal("100")

    return {
        "report_type": "daily",
        "as_of": report_date.isoformat(),
        "base_currency": _base_currency(config),
        "output_currency": _output_currency(config),
        "currency_conversion": _currency_conversion_summary(config),
        "portfolio_value": total,
        "holdings_value": holdings_total,
        "daily_change": daily_change,
        "daily_change_pct": daily_change_pct,
        "by_account": by_account,
        "account_reconciliation": reconciliation,
        "broker_check_mode": broker_check_mode
        or ("statement_import" if broker_total_requests else "broker_totals" if force_account_reconciliation else "current_price"),
        "broker_total_requests": broker_total_requests or [],
        "stale_account_values": stale_account_values,
        "quality": quality,
        "by_asset_type": by_asset_type,
        "concentration_alerts": concentration,
        "dividends": dividends,
        "actual_income": actual_income,
        "holdings": holding_rows,
        "risk_rows": holding_rows,
        "holdings_count": len(holdings),
        "price_quality": "stored_prices",
    }


def build_monthly_report(
    holdings: list[Holding],
    config: dict[str, Any],
    account_values: dict[str, AccountValue] | None = None,
    income_summaries: list[IncomeSummary] | None = None,
) -> dict[str, Any]:
    report_date = date.today()
    applicable_account_values = _applicable_account_values(account_values, report_date)
    holdings_total = sum((_market_value(holding, config) for holding in holdings), Decimal("0"))
    holdings_by_account = _sum_by_account_name(holdings, config)
    stale_account_values = _stale_account_values(
        account_values,
        report_date,
        account_labels=set(holdings_by_account),
    )
    by_account = _account_breakdown(holdings_by_account, applicable_account_values, config)
    total = sum(by_account.values(), Decimal("0")) if applicable_account_values else holdings_total
    signals = _sell_hold_signals(holdings, total, config)
    reconciliation = _account_reconciliation(holdings_by_account, applicable_account_values, config)
    return {
        "report_type": "monthly",
        "as_of": report_date.isoformat(),
        "base_currency": _base_currency(config),
        "output_currency": _output_currency(config),
        "currency_conversion": _currency_conversion_summary(config),
        "portfolio_value": total,
        "holdings_value": holdings_total,
        "by_account": by_account,
        "account_reconciliation": reconciliation,
        "stale_account_values": stale_account_values,
        "quality": _quality_summary(holdings, reconciliation),
        "by_asset_type": _sum_by_asset_type(holdings, config),
        "concentration_alerts": _concentration_alerts(holdings, total, config),
        "dividends": _dividend_summary(holdings, config),
        "actual_income": _actual_income_summary(income_summaries or []),
        "holdings": _holding_rows(holdings, total, config),
        "signals": signals,
        "notes": [
            "Use this as decision support, not financial advice.",
            "Review tax impact before selling taxable positions.",
            "Use new contributions for rebalancing before selling when practical.",
        ],
    }


def _sum_by(holdings: list[Holding], field: str, config: dict[str, Any]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in holdings:
        totals[getattr(holding, field)] += _market_value(holding, config)
    return dict(sorted(totals.items()))


def _sum_by_account_name(holdings: list[Holding], config: dict[str, Any]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in holdings:
        totals[_account_label(holding)] += _market_value(holding, config)
    return dict(sorted(totals.items()))


def _account_breakdown(
    holdings_by_account: dict[str, Decimal],
    account_values: dict[str, AccountValue] | None,
    config: dict[str, Any],
) -> dict[str, Decimal]:
    if not account_values:
        return holdings_by_account
    combined = dict(holdings_by_account)
    combined.update({account: _account_value_amount(value, config) for account, value in account_values.items()})
    return dict(sorted(combined.items()))


def _account_reconciliation(
    holdings_by_account: dict[str, Decimal],
    account_values: dict[str, AccountValue] | None,
    config: dict[str, Any],
) -> list[dict[str, Decimal | str]]:
    if not account_values:
        return []
    rows: list[dict[str, Decimal | str]] = []
    for account, account_value in sorted(account_values.items()):
        reported_value = _account_value_amount(account_value, config)
        holdings_value = holdings_by_account.get(account, Decimal("0"))
        difference = reported_value - holdings_value
        difference_pct = (difference / reported_value) * Decimal("100") if reported_value else Decimal("0")
        rows.append(
            {
                "account": account,
                "reported_value": reported_value,
                "parsed_holdings_value": holdings_value,
                "difference": difference,
                "difference_pct": difference_pct,
                "status": _reconciliation_status(difference, difference_pct),
            }
        )
    return rows


def _account_value_amount(value: AccountValue, config: dict[str, Any] | None = None) -> Decimal:
    if not isinstance(value, dict):
        return value
    amount = value["current_value"] if isinstance(value["current_value"], Decimal) else Decimal(str(value["current_value"]))
    currency = str(value.get("currency", _base_currency(config or {}))).upper()
    if config is None:
        return amount
    return amount * _rates_to_base(config).get(currency, Decimal("1"))


def _account_value_as_of(value: AccountValue) -> date | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("as_of")
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw))


def _applicable_account_values(
    account_values: dict[str, AccountValue] | None,
    report_date: date,
) -> dict[str, AccountValue]:
    if not account_values:
        return {}
    return {
        account: value
        for account, value in account_values.items()
        if (as_of := _account_value_as_of(value)) is None or as_of == report_date
    }


def _reconciliation_account_values(
    account_values: dict[str, AccountValue] | None,
    applicable_account_values: dict[str, AccountValue],
    force_account_reconciliation: bool,
    reconciliation_accounts: set[str] | None,
) -> dict[str, AccountValue]:
    if not force_account_reconciliation:
        return applicable_account_values
    if not reconciliation_accounts:
        return dict(applicable_account_values)
    return {
        account: value
        for account, value in applicable_account_values.items()
        if account in reconciliation_accounts
    }


def _stale_account_values(
    account_values: dict[str, AccountValue] | None,
    report_date: date,
    checked_accounts: set[str] | None = None,
    account_labels: set[str] | None = None,
) -> list[dict[str, Any]]:
    account_values = account_values or {}
    checked_accounts = checked_accounts or set()
    account_labels = account_labels or set(account_values)
    rows: list[dict[str, Any]] = []
    for account in sorted(account_labels | set(account_values)):
        if account in checked_accounts:
            continue
        value = account_values.get(account)
        if value is None:
            rows.append(
                {
                    "account": account,
                    "reported_value": None,
                    "as_of": "",
                    "report_as_of": report_date.isoformat(),
                    "status": "MISSING_CURRENT_TOTAL",
                }
            )
            continue
        as_of = _account_value_as_of(value)
        if as_of is None or as_of == report_date:
            continue
        rows.append(
            {
                "account": account,
                "reported_value": _account_value_amount(value),
                "as_of": as_of.isoformat(),
                "report_as_of": report_date.isoformat(),
                "status": "SKIPPED_STALE",
            }
        )
    return rows


def _reconciliation_status(difference: Decimal, difference_pct: Decimal) -> str:
    abs_difference = abs(difference)
    abs_pct = abs(difference_pct)
    if abs_difference <= Decimal("100") or abs_pct <= Decimal("0.25"):
        return "MATCHED"
    if abs_difference <= Decimal("1000") or abs_pct <= Decimal("1.00"):
        return "WATCH"
    return "REVIEW_REQUIRED"


def _quality_summary(
    holdings: list[Holding],
    reconciliation: list[dict[str, Decimal | str]],
) -> dict[str, Any]:
    issues = _quality_issues(holdings, reconciliation)
    by_severity: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
    return {
        "status": _quality_status(issues),
        "issue_count": len(issues),
        "by_severity": by_severity,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "remediation": issue.remediation,
                "symbol": issue.symbol,
                "account": issue.account,
            }
            for issue in issues
        ],
    }


def _quality_issues(
    holdings: list[Holding],
    reconciliation: list[dict[str, Decimal | str]],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    seen_symbols: set[tuple[str, str, str, str]] = set()
    for holding in holdings:
        account = _account_label(holding)
        symbol_key = (holding.account, account, holding.market, holding.symbol)
        if symbol_key in seen_symbols:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="DUPLICATE_ACTIVE_POSITION",
                    message=f"{holding.symbol} appears more than once for {account}/{holding.account}/{holding.market}.",
                    remediation="Confirm whether the statement contains duplicate lots or whether the importer should aggregate this broker format.",
                    symbol=holding.symbol,
                    account=account,
                )
            )
        seen_symbols.add(symbol_key)
        if holding.current_price is None:
            issues.append(
                QualityIssue(
                    severity="critical",
                    code="MISSING_PRICE",
                    message=f"{holding.symbol} has no current price, so its market value is treated as zero.",
                    remediation="Run refresh-prices or provide a manual price CSV before relying on performance calculations.",
                    symbol=holding.symbol,
                    account=account,
                )
            )
        if holding.cost_basis is None and holding.normalized_asset_type in {"stock", "etf", "mutual fund", "crypto"}:
            issues.append(
                QualityIssue(
                    severity="info",
                    code="MISSING_COST_BASIS",
                    message=f"{holding.symbol} has no cost basis; gain/loss will show as n/a.",
                    remediation="Import a cost-basis or tax-lot export for accurate gain/loss and tax-aware decisions.",
                    symbol=holding.symbol,
                    account=account,
                )
            )
    for row in reconciliation:
        if row["status"] == "REVIEW_REQUIRED":
            issues.append(
                QualityIssue(
                    severity="critical",
                    code="ACCOUNT_RECONCILIATION_GAP",
                    message=(
                        f"{row['account']} differs from broker-reported value by "
                        f"{row['difference']} ({row['difference_pct']:.2f}%)."
                    ),
                    remediation="Re-import the latest statement, refresh prices, and verify cash/crypto positions before making decisions.",
                    account=str(row["account"]),
                )
            )
        elif row["status"] == "WATCH":
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="ACCOUNT_RECONCILIATION_WATCH",
                    message=(
                        f"{row['account']} differs from broker-reported value by "
                        f"{row['difference']} ({row['difference_pct']:.2f}%)."
                    ),
                    remediation="Review timing differences, cash balances, unsettled trades, and provider price freshness.",
                    account=str(row["account"]),
                )
            )
    return issues


def _quality_status(issues: list[QualityIssue]) -> str:
    if any(issue.severity == "critical" for issue in issues):
        return "REVIEW_REQUIRED"
    if any(issue.severity == "warning" for issue in issues):
        return "WATCH"
    return "OK"


def _base_currency(config: dict[str, Any]) -> str:
    return str(config.get("base_currency", "USD")).upper()


def _output_currency(config: dict[str, Any]) -> str:
    reporting = config.get("reporting", {})
    if isinstance(reporting, dict) and reporting.get("output_currency"):
        return str(reporting["output_currency"]).upper()
    return _base_currency(config)


def _rates_to_base(config: dict[str, Any]) -> dict[str, Decimal]:
    conversion = config.get("currency_conversion", {})
    rates = conversion.get("rates_to_base", {}) if isinstance(conversion, dict) else {}
    if not isinstance(rates, dict) and isinstance(conversion, dict):
        rates = {
            currency: rate
            for currency, rate in conversion.items()
            if str(currency).upper() == str(currency) and currency != "rates_to_base"
        }
    result = {_base_currency(config): Decimal("1")}
    for currency, rate in rates.items():
        result[str(currency).upper()] = Decimal(str(rate))
    return result


def _currency_rate(holding: Holding, config: dict[str, Any]) -> Decimal:
    return _rates_to_base(config).get(holding.currency.upper(), Decimal("1"))


def _currency_conversion_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_currency": _base_currency(config),
        "rates_to_base": _rates_to_base(config),
    }


def _market_value(holding: Holding, config: dict[str, Any]) -> Decimal:
    return holding.market_value * _currency_rate(holding, config)


def _cost_basis(holding: Holding, config: dict[str, Any]) -> Decimal | None:
    if holding.cost_basis is None:
        return None
    return holding.cost_basis * _currency_rate(holding, config)


def _price(holding: Holding, config: dict[str, Any]) -> Decimal | None:
    if holding.current_price is None:
        return None
    return holding.current_price * _currency_rate(holding, config)


def _native_amount(value: Decimal | None, holding: Holding, config: dict[str, Any]) -> Decimal | None:
    if value is None or holding.currency.upper() == _base_currency(config):
        return None
    return value


def _sum_by_asset_type(holdings: list[Holding], config: dict[str, Any]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in holdings:
        totals[_display_asset_type(holding.normalized_asset_type)] += _market_value(holding, config)
    return dict(sorted(totals.items()))


def _holding_rows(holdings: list[Holding], total: Decimal, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for holding in holdings:
        market_value = _market_value(holding, config)
        cost_basis = _cost_basis(holding, config)
        gain_loss = _gain_loss(holding, config)
        gain_loss_pct = _gain_loss_pct(cost_basis, gain_loss)
        portfolio_pct = (market_value / total) * Decimal("100") if total else Decimal("0")
        annual_dividend = (
            holding.quantity * holding.annual_dividend_per_share * _currency_rate(holding, config)
            if holding.annual_dividend_per_share is not None
            else None
        )
        rows.append(
            {
                "account": _account_label(holding),
                "symbol": _display_symbol(holding),
                "name": _display_name(holding),
                "asset_type": _display_asset_type(holding.normalized_asset_type),
                "market": holding.market.upper(),
                "quantity": holding.quantity,
                "currency": holding.currency,
                "base_currency": _base_currency(config),
                "currency_rate": _currency_rate(holding, config),
                "price": _price(holding, config),
                "native_price": _native_amount(holding.current_price, holding, config),
                "market_value": market_value,
                "native_market_value": _native_amount(holding.market_value, holding, config),
                "cost_basis": cost_basis,
                "native_cost_basis": _native_amount(holding.cost_basis, holding, config),
                "gain_loss": gain_loss,
                "native_gain_loss": _native_amount(_gain_loss_native(holding), holding, config),
                "gain_loss_pct": gain_loss_pct,
                "portfolio_pct": portfolio_pct,
                "annual_dividend": annual_dividend,
                "risk_status": _risk_status(holding, portfolio_pct, config),
            }
        )
    return sorted(rows, key=lambda row: row["market_value"], reverse=True)


def _account_label(holding: Holding) -> str:
    if holding.broker:
        return holding.broker
    return holding.account


def _display_symbol(holding: Holding) -> str:
    if holding.normalized_asset_type != "mutual fund" or holding.market.upper() != "IN":
        return holding.symbol
    return _display_name(holding)


def _display_name(holding: Holding) -> str:
    if holding.normalized_asset_type != "mutual fund" or holding.market.upper() != "IN":
        return holding.name
    name = holding.name.strip() if holding.name else holding.symbol
    replacements = {
        " Reg ": " ",
        " Reg(": "(",
        " (G)": "",
        "(G)": "",
        "_G": "",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    return " ".join(name.split())


def _display_asset_type(asset_type: str) -> str:
    labels = {
        "mutual fund": "MF",
        "etf": "ETF",
        "stock": "Stock",
        "crypto": "Crypto",
        "cash": "Cash",
    }
    normalized = asset_type.strip().lower()
    return labels.get(normalized, normalized.title())


def _gain_loss(holding: Holding, config: dict[str, Any]) -> Decimal | None:
    cost_basis = _cost_basis(holding, config)
    if cost_basis is None:
        return None
    return _market_value(holding, config) - cost_basis


def _gain_loss_native(holding: Holding) -> Decimal | None:
    if holding.cost_basis is None:
        return None
    return holding.market_value - holding.cost_basis


def _gain_loss_pct(cost_basis: Decimal | None, gain_loss: Decimal | None) -> Decimal | None:
    if gain_loss is None or cost_basis is None or cost_basis <= 0:
        return None
    return (gain_loss / cost_basis) * Decimal("100")


def _risk_status(holding: Holding, portfolio_pct: Decimal, config: dict[str, Any]) -> str:
    risk = config.get("risk_profile", {})
    max_single_stock = Decimal(str(risk.get("max_single_stock_pct", 10)))
    watch_single_stock = Decimal(str(risk.get("watch_single_stock_pct", 7)))
    max_crypto = Decimal(str(risk.get("max_crypto_pct", 10)))
    asset_type = holding.normalized_asset_type
    if asset_type == "stock" and portfolio_pct >= max_single_stock:
        return "BREACH_SINGLE_STOCK_LIMIT"
    if asset_type == "stock" and portfolio_pct >= watch_single_stock:
        return "WATCH_SINGLE_STOCK_CONCENTRATION"
    if asset_type == "crypto" and portfolio_pct >= max_crypto:
        return "BREACH_CRYPTO_LIMIT"
    if asset_type == "crypto":
        return "WATCH_CRYPTO_VOLATILITY"
    if asset_type in {"etf", "mutual fund"}:
        return "DIVERSIFIED_FUND"
    return "OK"


def _concentration_alerts(holdings: list[Holding], total: Decimal, config: dict[str, Any]) -> list[str]:
    if total <= 0:
        return []
    risk = config.get("risk_profile", {})
    max_single_stock = Decimal(str(risk.get("max_single_stock_pct", 10)))
    watch_single_stock = Decimal(str(risk.get("watch_single_stock_pct", 7)))
    max_crypto = Decimal(str(risk.get("max_crypto_pct", 10)))

    alerts: list[str] = []
    crypto_total = Decimal("0")
    for holding in holdings:
        market_value = _market_value(holding, config)
        pct = (market_value / total) * Decimal("100")
        asset_type = holding.normalized_asset_type
        if asset_type == "crypto":
            crypto_total += market_value
        if asset_type == "stock" and pct >= max_single_stock:
            alerts.append(f"{holding.symbol} is {pct:.2f}% of portfolio, above {max_single_stock}% limit.")
        elif asset_type == "stock" and pct >= watch_single_stock:
            alerts.append(f"{holding.symbol} is {pct:.2f}% of portfolio, above {watch_single_stock}% watch level.")

    if crypto_total > 0:
        crypto_pct = (crypto_total / total) * Decimal("100")
        if crypto_pct >= max_crypto:
            alerts.append(f"Crypto is {crypto_pct:.2f}% of portfolio, above {max_crypto}% limit.")
    return alerts


def _dividend_summary(holdings: list[Holding], config: dict[str, Any]) -> dict[str, Decimal]:
    annual = Decimal("0")
    for holding in holdings:
        if holding.annual_dividend_per_share:
            annual += holding.quantity * holding.annual_dividend_per_share * _currency_rate(holding, config)
    return {
        "projected_annual": annual,
        "projected_monthly_average": annual / Decimal("12") if annual else Decimal("0"),
    }


def _actual_income_summary(summaries: list[IncomeSummary]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_dividends_period = Decimal("0")
    total_dividends_ytd = Decimal("0")
    total_interest_period = Decimal("0")
    total_interest_ytd = Decimal("0")
    total_other_period = Decimal("0")
    total_other_ytd = Decimal("0")
    for summary in summaries:
        dividends_period = summary.dividends_period or Decimal("0")
        dividends_ytd = summary.dividends_ytd or Decimal("0")
        interest_period = summary.interest_period or Decimal("0")
        interest_ytd = summary.interest_ytd or Decimal("0")
        other_period = summary.other_income_period or Decimal("0")
        other_ytd = summary.other_income_ytd or Decimal("0")
        rows.append(
            {
                "account": summary.broker,
                "statement_date": summary.statement_date.isoformat(),
                "dividends_period": dividends_period,
                "dividends_ytd": dividends_ytd,
                "interest_period": interest_period,
                "interest_ytd": interest_ytd,
                "other_income_period": other_period,
                "other_income_ytd": other_ytd,
            }
        )
        total_dividends_period += dividends_period
        total_dividends_ytd += dividends_ytd
        total_interest_period += interest_period
        total_interest_ytd += interest_ytd
        total_other_period += other_period
        total_other_ytd += other_ytd
    return {
        "rows": rows,
        "total_dividends_period": total_dividends_period,
        "total_dividends_ytd": total_dividends_ytd,
        "total_interest_period": total_interest_period,
        "total_interest_ytd": total_interest_ytd,
        "total_other_income_period": total_other_period,
        "total_other_income_ytd": total_other_ytd,
    }


def _sell_hold_signals(holdings: list[Holding], total: Decimal, config: dict[str, Any]) -> list[Signal]:
    if total <= 0:
        return []
    risk = config.get("risk_profile", {})
    max_single_stock = Decimal(str(risk.get("max_single_stock_pct", 10)))
    watch_single_stock = Decimal(str(risk.get("watch_single_stock_pct", 7)))
    signals: list[Signal] = []

    for holding in holdings:
        asset_type = holding.normalized_asset_type
        market_value = _market_value(holding, config)
        pct = (market_value / total) * Decimal("100")
        gain_loss_pct = None
        cost_basis = _cost_basis(holding, config)
        if cost_basis and cost_basis > 0:
            gain_loss_pct = ((market_value - cost_basis) / cost_basis) * Decimal("100")

        if asset_type == "stock" and pct >= max_single_stock:
            signals.append(
                Signal(
                    symbol=holding.symbol,
                    action="TRIM_CANDIDATE",
                    reason=f"Position is {pct:.2f}% of portfolio, above the {max_single_stock}% single-stock limit.",
                )
            )
        elif asset_type == "stock" and gain_loss_pct is not None and gain_loss_pct <= Decimal("-30"):
            signals.append(
                Signal(
                    symbol=holding.symbol,
                    action="WATCH",
                    reason=f"Unrealized return is {gain_loss_pct:.2f}%. Review thesis and tax-loss harvesting potential.",
                )
            )
        elif asset_type == "stock" and pct >= watch_single_stock:
            signals.append(
                Signal(
                    symbol=holding.symbol,
                    action="WATCH",
                    reason=f"Position is {pct:.2f}% of portfolio, above the {watch_single_stock}% watch level.",
                )
            )
        elif asset_type in {"etf", "mutual fund"}:
            signals.append(
                Signal(
                    symbol=holding.symbol,
                    action="HOLD",
                    reason="Diversified fund exposure. Review expense ratio, overlap, and allocation fit monthly.",
                )
            )
        elif asset_type == "crypto":
            signals.append(
                Signal(
                    symbol=holding.symbol,
                    action="WATCH",
                    reason=f"Crypto allocation contributes {pct:.2f}% to portfolio volatility. Keep within policy limit.",
                )
            )
        else:
            signals.append(
                Signal(
                    symbol=holding.symbol,
                    action="HOLD",
                    reason="No rule-based sell signal triggered. Recheck fundamentals during monthly review.",
                )
            )
    return signals
