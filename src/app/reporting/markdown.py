from __future__ import annotations

from pathlib import Path
from typing import Any

from app.reporting.serialization import money, pct, report_filename, write_latest_alias


def render_markdown(report: dict[str, Any]) -> str:
    fx_revaluation = report.get("fx_revaluation", {})
    lines = [
        f"# Portfolio {str(report.get('report_type', 'report')).title()} Report",
        "",
        f"- As of: {report.get('as_of')}",
        f"- Portfolio value: {money(report.get('portfolio_value'))}",
        f"- Holdings value: {money(report.get('holdings_value'))}",
    ]
    if isinstance(fx_revaluation, dict) and fx_revaluation.get("status") == "changed":
        lines.extend(
            [
                f"- Market daily change: {money(fx_revaluation.get('market_daily_change'))} ({pct(fx_revaluation.get('market_daily_change_pct'))})",
                f"- FX revaluation: {money(fx_revaluation.get('fx_impact'))}",
                f"- Total change after FX: {money(report.get('daily_change'))} ({pct(report.get('daily_change_pct'))})",
            ]
        )
    elif report.get("daily_change") is not None:
        lines.append(f"- Daily change: {money(report.get('daily_change'))} ({pct(report.get('daily_change_pct'))})")
    lines.extend(
        [
        f"- Quality status: {report.get('quality', {}).get('status', 'UNKNOWN')}",
        "",
        "## Accounts",
        "",
        "| Account | Value |",
        "|---|---:|",
        ]
    )
    for account, value in report.get("by_account", {}).items():
        lines.append(f"| {account} | {money(value)} |")

    lines.extend(["", "## Holdings", "", "| Symbol | Name | Value | Allocation | Gain/Loss | Risk |", "|---|---|---:|---:|---:|---|"])
    for row in report.get("holdings", []):
        lines.append(
            "| {symbol} | {name} | {value} | {allocation} | {gain_loss} | {risk} |".format(
                symbol=row["symbol"],
                name=row["name"],
                value=money(row["market_value"]),
                allocation=pct(row["portfolio_pct"]),
                gain_loss=money(row["gain_loss"]) if row["gain_loss"] is not None else "n/a",
                risk=row["risk_status"],
            )
        )

    alerts = report.get("concentration_alerts", [])
    lines.extend(["", "## Risk Alerts", ""])
    lines.extend([f"- {alert}" for alert in alerts] if alerts else ["- None"])

    issues = report.get("quality", {}).get("issues", [])
    lines.extend(["", "## Data Quality", ""])
    lines.extend([f"- {issue['severity']}: {issue['code']} - {issue['message']}" for issue in issues] if issues else ["- No issues found"])

    if report.get("signals"):
        lines.extend(["", "## Monthly Signals", ""])
        for signal in report["signals"]:
            lines.append(f"- {signal.symbol}: {signal.action} - {signal.reason}")

    return "\n".join(lines) + "\n"


def write_markdown_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / report_filename(report, "md")
    path.write_text(render_markdown(report), encoding="utf-8")
    write_latest_alias(path, "latest.md")
    return path
