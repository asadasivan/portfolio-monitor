from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.analysis import build_daily_report, build_monthly_report
from app.ingestion import load_holdings
from app.market_data import provider_symbol
from app.domain.models import Holding
from app.reporting.compact import render_ai_json, render_compact, render_manifest
from app.reporting.html import write_html_report
from app.persistence import PortfolioStore


def test_csv_import_loads_normalized_holdings(tmp_path: Path) -> None:
    holdings = load_holdings(_write_holdings_csv(tmp_path))
    assert len(holdings) == 4
    assert holdings[0].symbol == "VTI"
    assert holdings[0].market_value == Decimal("25000")


def test_store_upserts_and_marks_missing(tmp_path: Path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    store.initialize()
    try:
        holdings = _holdings()
        counts = store.upsert_holdings(holdings, source="full")
        assert counts["inserted_or_updated"] == 4
        assert counts["marked_missing"] == 0

        counts = store.upsert_holdings(holdings[:2], source="full")
        assert counts["inserted_or_updated"] == 2
        assert counts["marked_missing"] == 0
        assert len(store.active_holdings()) == 4
    finally:
        store.close()


def test_store_marks_missing_within_same_statement_scope(tmp_path: Path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    store.initialize()
    try:
        holdings = _holdings()
        extra_vti_lot = replace(
            holdings[0],
            symbol="VXUS",
            name="Vanguard Total International Stock ETF",
            quantity=Decimal("10"),
            cost_basis=Decimal("500"),
            current_price=Decimal("60"),
            sector="International",
            annual_dividend_per_share=Decimal("2"),
        )
        store.upsert_holdings([holdings[0], extra_vti_lot], source="full")
        counts = store.upsert_holdings([holdings[0]], source="full")
        assert counts["marked_missing"] == 1
        assert len(store.active_holdings()) == 1
    finally:
        store.close()


def test_store_updates_prices(tmp_path: Path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    store.initialize()
    try:
        store.upsert_holdings(_holdings(), source="full")
        counts = store.update_prices([{"symbol": "VTI", "market": "US", "current_price": "251.25"}])
        assert counts["updated"] == 1
        updated = [holding for holding in store.active_holdings() if holding.symbol == "VTI"][0]
        assert updated.current_price == Decimal("251.25")
    finally:
        store.close()


def test_store_updates_cost_basis_from_average_cost(tmp_path: Path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    store.initialize()
    try:
        store.upsert_holdings(_holdings(), source="full")
        counts = store.update_cost_basis(
            [{"broker": "Broker A", "market": "US", "symbol": "VTI", "average_cost": "200"}]
        )
        assert counts["updated"] == 1
        updated = [holding for holding in store.active_holdings() if holding.symbol == "VTI"][0]
        assert updated.cost_basis == Decimal("20000")
    finally:
        store.close()


def test_newer_statement_date_wins(tmp_path: Path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.db")
    store.initialize()
    try:
        holding = _holdings()[0]
        newer = replace(holding, current_price=Decimal("300"))
        older = replace(holding, current_price=Decimal("200"), statement_date=holding.statement_date.replace(year=2025))
        store.upsert_holdings([newer], source="newer")
        counts = store.upsert_holdings([older], source="older")
        assert counts["inserted_or_updated"] == 0
        stored = store.active_holdings()[0]
        assert stored.current_price == Decimal("300")
    finally:
        store.close()


def test_provider_symbol_maps_crypto_and_india_symbols() -> None:
    holdings = _holdings()
    symbols = {holding.symbol: provider_symbol(holding) for holding in holdings}
    assert symbols["BTC"] == "BTC-USD"
    assert symbols["VTI"] == "VTI"
    india_holding = Holding(
        account="India Account",
        broker="Broker C",
        market="IN",
        symbol="RELIANCE.NSE",
        name="Reliance Industries",
        asset_type="Stock",
        quantity=Decimal("10"),
        cost_basis=Decimal("25000"),
        current_price=Decimal("2900"),
        currency="INR",
        sector="Energy",
        statement_date=holdings[0].statement_date,
        annual_dividend_per_share=Decimal("10"),
    )
    assert provider_symbol(india_holding) == "RELIANCE.NS"


def test_daily_report_builds_compact_summary() -> None:
    report = build_daily_report(_holdings(), Decimal("80000"), _config())
    assert report["report_type"] == "daily"
    assert report["portfolio_value"] == Decimal("74200.0")
    assert report["daily_change"] == Decimal("-5800.0")
    assert report["dividends"]["projected_annual"] > 0
    assert report["quality"]["status"] == "OK"


def test_daily_report_flags_missing_price_and_cost_basis() -> None:
    holding = replace(_holdings()[1], current_price=None, cost_basis=None)
    report = build_daily_report([holding], None, _config())
    codes = {issue["code"] for issue in report["quality"]["issues"]}
    assert report["quality"]["status"] == "REVIEW_REQUIRED"
    assert "MISSING_PRICE" in codes
    assert "MISSING_COST_BASIS" in codes


def test_compact_ai_outputs_are_small_and_structured() -> None:
    report = build_daily_report(_holdings(), Decimal("80000"), _config())
    compact = render_compact(report)
    ai_json = render_ai_json(report)
    manifest = render_manifest(report)
    assert "latest.ai.json" in manifest
    assert "low_token_portfolio_analysis_context" in ai_json
    assert "top_holdings=" in compact
    assert len(compact) < 2000


def test_html_report_has_interactive_holdings_and_risk_controls(tmp_path: Path) -> None:
    report = build_daily_report(_holdings(), Decimal("80000"), _config())
    path = write_html_report(report, tmp_path)
    html = path.read_text(encoding="utf-8")

    assert (tmp_path / "latest.html").exists()
    assert "Holdings Detail" in html
    assert "Last Price" in html
    assert "250.00" in html
    assert "Risk By Holding" in html
    assert "Report Checks" in html
    assert "Run Context" not in html
    assert "checks-grid" in html
    assert "Broker total check" in html
    assert "Price freshness" in html
    assert "section-account" in html
    assert "section-asset" in html
    assert "section-dividend" in html
    assert "section-disclaimer" in html
    assert ".issue-tag.warning" in html
    assert ".issue-tag.info" in html
    assert html.count("<table data-interactive='true'>") == 2
    assert 'className = "column-picker"' in html
    assert 'className = "column-options"' in html
    assert 'className = "reset-button"' in html
    assert 'classList.add("sortable")' in html
    assert "Search this table" in html


def test_html_report_shows_all_data_quality_issues(tmp_path: Path) -> None:
    holdings = [replace(holding, cost_basis=None) for holding in _holdings()]
    report = build_daily_report(holdings, Decimal("80000"), _config())
    path = write_html_report(report, tmp_path)
    html = path.read_text(encoding="utf-8")

    assert "View all issues" in html
    assert "more issues not shown" not in html
    assert html.count('class="issue-item severity-info"') == len(holdings)


def test_monthly_report_includes_signals() -> None:
    report = build_monthly_report(_holdings(), _config())
    assert report["report_type"] == "monthly"
    assert report["signals"]


def _write_holdings_csv(tmp_path: Path) -> Path:
    path = tmp_path / "holdings.csv"
    path.write_text(
        "\n".join(
            [
                "account,broker,market,symbol,name,asset_type,quantity,cost_basis,current_price,currency,sector,statement_date,annual_dividend_per_share",
                "Long-Term Account,Broker A,US,VTI,Vanguard Total Stock Market ETF,ETF,100,22000,250,USD,Broad Market,2026-07-04,3.60",
                "Long-Term Account,Broker A,US,VXUS,Vanguard Total International Stock ETF,ETF,200,11000,60,USD,International,2026-07-04,2.00",
                "Trading Account,Broker B,US,AAPL,Apple Inc,Stock,20,3000,210,USD,Technology,2026-07-04,1.04",
                "Crypto Account,Crypto Broker,GLOBAL,BTC,Bitcoin,Crypto,0.5,25000,66000,USD,Crypto,2026-07-04,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _holdings() -> list[Holding]:
    statement_date = date(2026, 7, 4)
    return [
        Holding(
            account="Long-Term Account",
            broker="Broker A",
            market="US",
            symbol="VTI",
            name="Vanguard Total Stock Market ETF",
            asset_type="ETF",
            quantity=Decimal("100"),
            cost_basis=Decimal("22000"),
            current_price=Decimal("250"),
            currency="USD",
            sector="Broad Market",
            statement_date=statement_date,
            annual_dividend_per_share=Decimal("3.60"),
        ),
        Holding(
            account="Long-Term Account",
            broker="Broker A",
            market="US",
            symbol="VXUS",
            name="Vanguard Total International Stock ETF",
            asset_type="ETF",
            quantity=Decimal("200"),
            cost_basis=Decimal("11000"),
            current_price=Decimal("60"),
            currency="USD",
            sector="International",
            statement_date=statement_date,
            annual_dividend_per_share=Decimal("2.00"),
        ),
        Holding(
            account="Trading Account",
            broker="Broker B",
            market="US",
            symbol="AAPL",
            name="Apple Inc",
            asset_type="Stock",
            quantity=Decimal("20"),
            cost_basis=Decimal("3000"),
            current_price=Decimal("210"),
            currency="USD",
            sector="Technology",
            statement_date=statement_date,
            annual_dividend_per_share=Decimal("1.04"),
        ),
        Holding(
            account="Crypto Account",
            broker="Crypto Broker",
            market="GLOBAL",
            symbol="BTC",
            name="Bitcoin",
            asset_type="Crypto",
            quantity=Decimal("0.5"),
            cost_basis=Decimal("25000"),
            current_price=Decimal("66000"),
            currency="USD",
            sector="Crypto",
            statement_date=statement_date,
            annual_dividend_per_share=Decimal("0"),
        ),
    ]


def _config() -> dict:
    return {
        "risk_profile": {
            "max_single_stock_pct": 10,
            "watch_single_stock_pct": 7,
            "max_crypto_pct": 10,
        }
    }
