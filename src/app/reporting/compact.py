from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.reporting.serialization import money, pct, report_filename, to_jsonable, write_latest_alias

MAX_AI_RECONCILIATION_ROWS = 20
MAX_AI_QUALITY_ISSUES = 25
MAX_AI_BROKER_REQUESTS = 20
MAX_AI_STALE_ACCOUNT_VALUES = 20
MAX_AI_RISK_ALERTS = 20
MAX_AI_TOP_HOLDINGS = 10


def render_compact(report: dict[str, Any]) -> str:
    top_holdings = ", ".join(
        f"{row['symbol']} {money(row['market_value'])} ({pct(row['portfolio_pct'])})"
        for row in report.get("holdings", [])[:5]
    )
    alerts = report.get("concentration_alerts", [])
    quality = report.get("quality", {})
    lines = [
        f"report_type={report.get('report_type')}",
        f"as_of={report.get('as_of')}",
        f"portfolio_value={money(report.get('portfolio_value'))}",
        f"holdings_value={money(report.get('holdings_value'))}",
        f"daily_change={money(report.get('daily_change')) if report.get('daily_change') is not None else 'n/a'}",
        f"daily_change_pct={pct(report.get('daily_change_pct')) if report.get('daily_change_pct') is not None else 'n/a'}",
        f"fx_impact={money(report.get('fx_revaluation', {}).get('fx_impact')) if report.get('fx_revaluation', {}).get('fx_impact') is not None else 'n/a'}",
        f"market_daily_change={money(report.get('fx_revaluation', {}).get('market_daily_change')) if report.get('fx_revaluation', {}).get('market_daily_change') is not None else 'n/a'}",
        f"quality_status={quality.get('status', 'UNKNOWN')}",
        f"quality_issues={quality.get('issue_count', 0)}",
        f"top_holdings={top_holdings or 'none'}",
        f"risk_alerts={'; '.join(alerts) if alerts else 'none'}",
    ]
    return "\n".join(lines) + "\n"


def render_ai_json(report: dict[str, Any]) -> str:
    income = report.get("actual_income", {})
    quality = _compact_quality(report.get("quality", {}))
    payload = {
        "low_token_portfolio_analysis_context": to_jsonable(
            {
                "report_type": report.get("report_type"),
                "as_of": report.get("as_of"),
                "base_currency": report.get("base_currency"),
                "output_currency": report.get("output_currency"),
                "portfolio_value": report.get("portfolio_value"),
                "holdings_value": report.get("holdings_value"),
                "daily_change": report.get("daily_change"),
                "daily_change_pct": report.get("daily_change_pct"),
                "fx_revaluation": report.get("fx_revaluation", {}),
                "by_account": report.get("by_account", {}),
                "account_reconciliation": _bounded_list(report.get("account_reconciliation", []), MAX_AI_RECONCILIATION_ROWS),
                "broker_check_mode": report.get("broker_check_mode"),
                "broker_total_requests": _bounded_list(report.get("broker_total_requests", []), MAX_AI_BROKER_REQUESTS),
                "stale_account_values": _bounded_list(report.get("stale_account_values", []), MAX_AI_STALE_ACCOUNT_VALUES),
                "quality": quality,
                "by_asset_type": report.get("by_asset_type", {}),
                "concentration_alerts": _bounded_list(report.get("concentration_alerts", []), MAX_AI_RISK_ALERTS),
                "dividends": report.get("dividends", {}),
                "actual_income": {
                    "total_dividends_period": income.get("total_dividends_period"),
                    "total_dividends_ytd": income.get("total_dividends_ytd"),
                    "total_interest_period": income.get("total_interest_period"),
                    "total_interest_ytd": income.get("total_interest_ytd"),
                    "total_other_income_period": income.get("total_other_income_period"),
                    "total_other_income_ytd": income.get("total_other_income_ytd"),
                },
                "top_holdings": [_compact_holding(row) for row in report.get("holdings", [])[:MAX_AI_TOP_HOLDINGS]],
                "signals": _bounded_list(report.get("signals", []), MAX_AI_RISK_ALERTS),
                "notes": _bounded_list(report.get("notes", []), MAX_AI_RISK_ALERTS),
            }
        )
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"


def _bounded_list(values: Any, limit: int) -> list[Any] | dict[str, Any]:
    if not isinstance(values, list):
        return []
    if len(values) <= limit:
        return values
    return {
        "items": values[:limit],
        "total_count": len(values),
        "omitted_count": len(values) - limit,
    }


def _compact_quality(quality: Any) -> dict[str, Any]:
    if not isinstance(quality, dict):
        quality = {}
    issues = quality.get("issues", [])
    compact = {
        "status": quality.get("status", "UNKNOWN"),
        "issue_count": quality.get("issue_count", 0),
        "by_severity": quality.get("by_severity", {}),
    }
    compact["issues"] = _bounded_list(issues if isinstance(issues, list) else [], MAX_AI_QUALITY_ISSUES)
    return compact


def _compact_holding(row: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "symbol": row.get("symbol"),
        "account": row.get("account"),
        "type": row.get("asset_type"),
        "market": row.get("market"),
        "value": row.get("market_value"),
        "pct": row.get("portfolio_pct"),
        "gain_loss": row.get("gain_loss"),
        "gain_loss_pct": row.get("gain_loss_pct"),
        "risk": row.get("risk_status"),
    }
    native_value = row.get("native_market_value")
    if native_value is not None:
        compact["native_value"] = native_value
        compact["currency"] = row.get("currency")
    return compact


def render_manifest(report: dict[str, Any]) -> str:
    payload = {
        "as_of": report.get("as_of"),
        "report_type": report.get("report_type"),
        "artifacts": {
            "human_html": "reports/latest.html",
            "assistant_json": "reports/latest.ai.json",
            "compact_text": "reports/latest.compact.txt",
            "markdown": "reports/latest.md",
        },
        "routing": {
            "assistant_default": "reports/latest.ai.json",
            "human_default": "reports/latest.html",
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_compact_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    compact_path = report_dir / report_filename(report, "compact.txt")
    compact_path.write_text(render_compact(report), encoding="utf-8")
    write_latest_alias(compact_path, "latest.compact.txt")

    ai_path = report_dir / report_filename(report, "ai.json")
    ai_path.write_text(render_ai_json(report), encoding="utf-8")
    write_latest_alias(ai_path, "latest.ai.json")

    manifest_path = report_dir / report_filename(report, "manifest.json")
    manifest_path.write_text(render_manifest(report), encoding="utf-8")
    write_latest_alias(manifest_path, "latest.manifest.json")
    return compact_path
