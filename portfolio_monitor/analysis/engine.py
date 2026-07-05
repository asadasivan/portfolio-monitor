from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_monitor.models import Holding, IncomeSummary, QualityIssue


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: str
    reason: str


def build_daily_report(
    holdings: list[Holding],
    previous_total: Decimal | None,
    config: dict[str, Any],
    account_values: dict[str, Decimal] | None = None,
    income_summaries: list[IncomeSummary] | None = None,
) -> dict[str, Any]:
    holdings_total = sum((holding.market_value for holding in holdings), Decimal("0"))
    holdings_by_account = _sum_by_account_name(holdings)
    by_account = _account_breakdown(holdings_by_account, account_values)
    total = sum(by_account.values(), Decimal("0")) if account_values else holdings_total
    by_asset_type = _sum_by_asset_type(holdings)
    concentration = _concentration_alerts(holdings, total, config)
    dividends = _dividend_summary(holdings)
    actual_income = _actual_income_summary(income_summaries or [])
    holding_rows = _holding_rows(holdings, total, config)
    reconciliation = _account_reconciliation(holdings_by_account, account_values)
    quality = _quality_summary(holdings, reconciliation)
    daily_change = None
    daily_change_pct = None
    if previous_total and previous_total > 0:
        daily_change = total - previous_total
        daily_change_pct = (daily_change / previous_total) * Decimal("100")

    return {
        "report_type": "daily",
        "as_of": date.today().isoformat(),
        "portfolio_value": total,
        "holdings_value": holdings_total,
        "daily_change": daily_change,
        "daily_change_pct": daily_change_pct,
        "by_account": by_account,
        "account_reconciliation": reconciliation,
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
    account_values: dict[str, Decimal] | None = None,
    income_summaries: list[IncomeSummary] | None = None,
) -> dict[str, Any]:
    holdings_total = sum((holding.market_value for holding in holdings), Decimal("0"))
    holdings_by_account = _sum_by_account_name(holdings)
    by_account = _account_breakdown(holdings_by_account, account_values)
    total = sum(by_account.values(), Decimal("0")) if account_values else holdings_total
    signals = _sell_hold_signals(holdings, total, config)
    reconciliation = _account_reconciliation(holdings_by_account, account_values)
    return {
        "report_type": "monthly",
        "as_of": date.today().isoformat(),
        "portfolio_value": total,
        "holdings_value": holdings_total,
        "by_account": by_account,
        "account_reconciliation": reconciliation,
        "quality": _quality_summary(holdings, reconciliation),
        "by_asset_type": _sum_by_asset_type(holdings),
        "concentration_alerts": _concentration_alerts(holdings, total, config),
        "dividends": _dividend_summary(holdings),
        "actual_income": _actual_income_summary(income_summaries or []),
        "holdings": _holding_rows(holdings, total, config),
        "signals": signals,
        "notes": [
            "Use this as decision support, not financial advice.",
            "Review tax impact before selling taxable positions.",
            "Use new contributions for rebalancing before selling when practical.",
        ],
    }


def _sum_by(holdings: list[Holding], field: str) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in holdings:
        totals[getattr(holding, field)] += holding.market_value
    return dict(sorted(totals.items()))


def _sum_by_account_name(holdings: list[Holding]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in holdings:
        totals[_account_label(holding)] += holding.market_value
    return dict(sorted(totals.items()))


def _account_breakdown(
    holdings_by_account: dict[str, Decimal],
    account_values: dict[str, Decimal] | None,
) -> dict[str, Decimal]:
    if not account_values:
        return holdings_by_account
    combined = dict(holdings_by_account)
    combined.update(account_values)
    return dict(sorted(combined.items()))


def _account_reconciliation(
    holdings_by_account: dict[str, Decimal],
    account_values: dict[str, Decimal] | None,
) -> list[dict[str, Decimal | str]]:
    if not account_values:
        return []
    rows: list[dict[str, Decimal | str]] = []
    for account, reported_value in sorted(account_values.items()):
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
    seen_symbols: set[tuple[str, str, str]] = set()
    for holding in holdings:
        account = _account_label(holding)
        symbol_key = (account, holding.market, holding.symbol)
        if symbol_key in seen_symbols:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="DUPLICATE_ACTIVE_POSITION",
                    message=f"{holding.symbol} appears more than once for {account}/{holding.market}.",
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


def _sum_by_asset_type(holdings: list[Holding]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for holding in holdings:
        totals[holding.normalized_asset_type] += holding.market_value
    return dict(sorted(totals.items()))


def _holding_rows(holdings: list[Holding], total: Decimal, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for holding in holdings:
        market_value = holding.market_value
        gain_loss = _gain_loss(holding)
        gain_loss_pct = _gain_loss_pct(holding, gain_loss)
        portfolio_pct = (market_value / total) * Decimal("100") if total else Decimal("0")
        annual_dividend = (
            holding.quantity * holding.annual_dividend_per_share
            if holding.annual_dividend_per_share is not None
            else None
        )
        rows.append(
            {
                "account": _account_label(holding),
                "symbol": holding.symbol,
                "name": holding.name,
                "asset_type": holding.normalized_asset_type,
                "quantity": holding.quantity,
                "price": holding.current_price,
                "market_value": market_value,
                "cost_basis": holding.cost_basis,
                "gain_loss": gain_loss,
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


def _gain_loss(holding: Holding) -> Decimal | None:
    if holding.cost_basis is None:
        return None
    return holding.market_value - holding.cost_basis


def _gain_loss_pct(holding: Holding, gain_loss: Decimal | None) -> Decimal | None:
    if gain_loss is None or holding.cost_basis is None or holding.cost_basis <= 0:
        return None
    return (gain_loss / holding.cost_basis) * Decimal("100")


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
        pct = (holding.market_value / total) * Decimal("100")
        asset_type = holding.normalized_asset_type
        if asset_type == "crypto":
            crypto_total += holding.market_value
        if asset_type == "stock" and pct >= max_single_stock:
            alerts.append(f"{holding.symbol} is {pct:.2f}% of portfolio, above {max_single_stock}% limit.")
        elif asset_type == "stock" and pct >= watch_single_stock:
            alerts.append(f"{holding.symbol} is {pct:.2f}% of portfolio, above {watch_single_stock}% watch level.")

    if crypto_total > 0:
        crypto_pct = (crypto_total / total) * Decimal("100")
        if crypto_pct >= max_crypto:
            alerts.append(f"Crypto is {crypto_pct:.2f}% of portfolio, above {max_crypto}% limit.")
    return alerts


def _dividend_summary(holdings: list[Holding]) -> dict[str, Decimal]:
    annual = Decimal("0")
    for holding in holdings:
        if holding.annual_dividend_per_share:
            annual += holding.quantity * holding.annual_dividend_per_share
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
        pct = (holding.market_value / total) * Decimal("100")
        gain_loss_pct = None
        if holding.cost_basis and holding.cost_basis > 0:
            gain_loss_pct = ((holding.market_value - holding.cost_basis) / holding.cost_basis) * Decimal("100")

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
