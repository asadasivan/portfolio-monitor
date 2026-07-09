from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.analysis import build_daily_report, build_monthly_report
from app.cli import _refresh_fx_rates
from app.ingestion import load_holdings
from app.ingestion.pdf_importer import _parse_indian_mutual_fund_valuation
from app.market_data import provider_symbol
from app.market_data.online import FxRateResult, fetch_fx_rates, _split_indian_mutual_funds
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


def test_fetch_fx_rates_uses_direct_yahoo_pair(monkeypatch) -> None:
    def fake_fetch(symbol: str, timeout_seconds: int) -> Decimal | None:
        assert timeout_seconds == 7
        return {"EURUSD=X": Decimal("1.09")}.get(symbol)

    monkeypatch.setattr("app.market_data.online._fetch_yahoo_price", fake_fetch)

    results = fetch_fx_rates("USD", {"EUR"}, "yahoo:7")

    assert results[0].currency == "EUR"
    assert results[0].base_currency == "USD"
    assert results[0].rate_to_base == Decimal("1.09")
    assert results[0].provider_symbol == "EURUSD=X"
    assert results[0].status == "ok"


def test_fetch_fx_rates_uses_inverse_yahoo_pair(monkeypatch) -> None:
    def fake_fetch(symbol: str, timeout_seconds: int) -> Decimal | None:
        return {"USDINR=X": Decimal("83.3333333333")}.get(symbol)

    monkeypatch.setattr("app.market_data.online._fetch_yahoo_price", fake_fetch)

    results = fetch_fx_rates("USD", {"INR"}, "yahoo")

    assert results[0].currency == "INR"
    assert results[0].provider_symbol == "USDINR=X"
    assert results[0].status == "ok"
    assert results[0].rate_to_base is not None
    assert results[0].rate_to_base.quantize(Decimal("0.0001")) == Decimal("0.0120")


def test_refresh_fx_rates_preserves_flattened_config_fallback(monkeypatch) -> None:
    config = {
        "base_currency": "USD",
        "currency_conversion": {"rates_to_base": "", "USD": 1, "INR": "0.012"},
        "market_data": {"provider": "yahoo"},
    }

    def fake_fetch(base_currency: str, currencies: set[str], provider: str) -> list[FxRateResult]:
        return [
            FxRateResult("USD", "USD", Decimal("1"), "USD", "ok"),
            FxRateResult("INR", "USD", Decimal("0.0105"), "USDINR=X", "ok"),
        ]

    monkeypatch.setattr("app.cli.fetch_fx_rates", fake_fetch)

    failures = _refresh_fx_rates(config, None, 6)

    assert failures == 0
    assert config["currency_conversion"]["rates_to_base"]["INR"] == Decimal("0.0105")
    assert config["_fx_refresh"]["previous_rates_to_base"]["INR"] == Decimal("0.012")
    assert config["_fx_refresh"]["changed_currencies"] == ["INR"]


def test_sift_capital_valuation_report_parses_mutual_fund_holdings() -> None:
    text = """
ARUNKUMAR SADASIVAN (PAN : AKVPA2621E)
Valuation Report as on 04/07/2026
Balance Purchase Market
Folio Scheme / Scrip Sub Category
Units Cost Value
Mutual Fund
5907287/39 HSBC Large Cap Fund (G) Equity: Large Cap 3,760.0621 11,41,581.05 17,94,267.04
599346552872 UTI Nifty 50 Index Fund (G) Equity: Index 12,748.6370 20,75,121.19 21,41,086.41
Mutual Fund Total : 32,16,702.24 39,35,353.45
"""
    holdings = _parse_indian_mutual_fund_valuation(text, broker="Sift Capital")

    assert len(holdings) == 2
    assert holdings[0].account == "Indian Mutual Funds"
    assert holdings[0].broker == "Sift Capital"
    assert holdings[0].market == "IN"
    assert holdings[0].asset_type == "Mutual Fund"
    assert holdings[0].currency == "INR"
    assert holdings[0].quantity == Decimal("3760.0621")
    assert holdings[0].cost_basis == Decimal("1141581.05")
    assert holdings[0].market_value.quantize(Decimal("0.01")) == Decimal("1794267.04")
    assert holdings[0].statement_date == date(2026, 7, 4)


def test_indian_mutual_fund_valuation_parser_is_schema_driven() -> None:
    text = """
BROKER REPORT
Valuation Report as on 04/07/2026
Balance Purchase Market
Folio Scheme / Scrip Sub Category
Units Cost Value
Mutual Fund
12678655 Parag Parikh Flexi Cap Fund Reg (G) Equity: Flexi Cap 26,266.2660 12,64,717.44 21,87,181.46
Mutual Fund Total : 12,64,717.44 21,87,181.46
"""
    holdings = _parse_indian_mutual_fund_valuation(text, broker="Generic Broker")

    assert len(holdings) == 1
    assert holdings[0].account == "Indian Mutual Funds"
    assert holdings[0].broker == "Generic Broker"
    assert holdings[0].name == "Parag Parikh Flexi Cap Fund Reg (G)"


def test_yahoo_provider_routes_indian_mutual_funds_to_amfi() -> None:
    india_mf = Holding(
        account="Indian Mutual Funds",
        broker="Sift Capital",
        market="IN",
        symbol="MF_123_PARAG_PARIKH_FLEXI_CAP_FUND_G",
        name="Parag Parikh Flexi Cap Fund Reg (G)",
        asset_type="Mutual Fund",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000"),
        current_price=Decimal("120"),
        currency="INR",
        sector="Equity: Flexi Cap",
        statement_date=date(2026, 7, 4),
    )
    us_stock = replace(_holdings()[2], symbol="AAPL")

    india_mfs, other_holdings = _split_indian_mutual_funds([india_mf, us_stock])

    assert india_mfs == [india_mf]
    assert other_holdings == [us_stock]


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


def test_daily_report_forces_broker_check_for_new_statement_accounts() -> None:
    today = date.today().isoformat()
    account_values = {
        "Broker A": {
            "current_value": Decimal("36000"),
            "currency": "USD",
            "as_of": "2026-01-01",
        }
    }
    current_account_values = {
        "Broker A": {
            "current_value": Decimal("36000"),
            "currency": "USD",
            "as_of": today,
        },
        "Broker B": {
            "current_value": Decimal("4200"),
            "currency": "USD",
            "as_of": today,
        },
    }
    normal_report = build_daily_report(_holdings(), Decimal("80000"), _config(), account_values)
    forced_stale_report = build_daily_report(
        _holdings(),
        Decimal("80000"),
        _config(),
        account_values,
        force_account_reconciliation=True,
        reconciliation_accounts={"Broker A"},
        broker_total_requests=[
            {
                "account": "Broker A",
                "statement_as_of": "2026-01-01",
                "required_as_of": today,
                "reason": "statement_not_current_day",
            }
        ],
    )
    forced_current_report = build_daily_report(
        _holdings(),
        Decimal("80000"),
        _config(),
        current_account_values,
        force_account_reconciliation=True,
        reconciliation_accounts=None,
    )

    assert normal_report["account_reconciliation"] == []
    assert normal_report["stale_account_values"][0]["account"] == "Broker A"
    assert forced_stale_report["broker_check_mode"] == "statement_import"
    assert forced_stale_report["account_reconciliation"] == []
    assert forced_stale_report["broker_total_requests"][0]["account"] == "Broker A"
    assert forced_current_report["broker_check_mode"] == "broker_totals"
    assert {row["account"] for row in forced_current_report["account_reconciliation"]} == {"Broker A", "Broker B"}
    assert forced_current_report["stale_account_values"] == [
        {
            "account": "Crypto Broker",
            "reported_value": None,
            "as_of": "",
            "report_as_of": today,
            "status": "MISSING_CURRENT_TOTAL",
        }
    ]


def test_compact_ai_outputs_are_small_and_structured() -> None:
    report = build_daily_report(_holdings(), Decimal("80000"), _config())
    compact = render_compact(report)
    ai_json = render_ai_json(report)
    manifest = render_manifest(report)
    assert "latest.ai.json" in manifest
    assert "low_token_portfolio_analysis_context" in ai_json
    assert "top_holdings=" in compact
    assert len(compact) < 2000
    assert len(ai_json) < 5000


def test_html_report_has_interactive_holdings_and_risk_controls(tmp_path: Path) -> None:
    report = build_daily_report(_holdings(), Decimal("80000"), _config())
    path = write_html_report(report, tmp_path)
    html = path.read_text(encoding="utf-8")

    assert (tmp_path / "latest.html").exists()
    assert "US Stocks and ETF" in html
    assert "India MF and Stocks" in html
    assert "Crypto" in html
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
    assert html.count("<table data-interactive") == 4
    assert html.count('class="total-row') == 2
    assert "14.44%" in html
    assert "32.00%" in html
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


def test_html_report_marks_negative_value_and_cost_cells_red(tmp_path: Path) -> None:
    report = build_daily_report(_holdings()[:1], None, _config())
    row = report["holdings"][0]
    row["price"] = Decimal("-1")
    row["market_value"] = Decimal("-100")
    row["cost_basis"] = Decimal("-90")
    row["annual_dividend"] = Decimal("-5")

    html = write_html_report(report, tmp_path).read_text(encoding="utf-8")

    assert '<td class="negative">-1.00</td>' in html
    assert '<td class="negative">-100.00</td>' in html
    assert '<td class="negative">-90.00</td>' in html
    assert '<td class="negative">-5.00</td>' in html


def test_report_converts_inr_holdings_to_base_currency_and_shows_native_value(tmp_path: Path) -> None:
    holding = Holding(
        account="Indian Mutual Funds",
        broker="Sift Capital",
        market="IN",
        symbol="MF_TEST",
        name="Example Indian MF",
        asset_type="Mutual Fund",
        quantity=Decimal("100"),
        cost_basis=Decimal("9000"),
        current_price=Decimal("100"),
        currency="INR",
        sector="Equity: Flexi Cap",
        statement_date=date(2026, 7, 4),
        annual_dividend_per_share=Decimal("0"),
    )
    config = _config()
    config["base_currency"] = "USD"
    config["currency_conversion"] = {"rates_to_base": {"USD": 1, "INR": "0.012"}}

    report = build_daily_report([holding], None, config)
    row = report["holdings"][0]

    assert report["portfolio_value"] == Decimal("120.000")
    assert row["market_value"] == Decimal("120.000")
    assert row["native_market_value"] == Decimal("10000")
    assert row["cost_basis"] == Decimal("108.000")
    assert row["native_cost_basis"] == Decimal("9000")

    html = write_html_report(report, tmp_path).read_text(encoding="utf-8")
    assert "120.00 (INR 10,000.00)" in html
    assert "108.00 (INR 9,000.00)" in html


def test_html_report_uses_configured_output_currency(tmp_path: Path) -> None:
    config = _config()
    config["base_currency"] = "USD"
    config["currency_conversion"] = {"rates_to_base": {"USD": 1, "INR": "0.012"}}
    config["reporting"] = {"output_currency": "INR"}

    report = build_daily_report(_holdings()[:1], None, config)
    html = write_html_report(report, tmp_path).read_text(encoding="utf-8")

    assert "Portfolio Value (INR)" in html
    assert "Value (INR)" in html
    assert "Market Value (INR)" in html
    assert "2,083,333.33" in html


def test_daily_report_splits_fx_revaluation_from_market_change(tmp_path: Path) -> None:
    holding = Holding(
        account="Indian Mutual Funds",
        broker="Sift Capital",
        market="IN",
        symbol="MF_TEST",
        name="Example Indian MF",
        asset_type="Mutual Fund",
        quantity=Decimal("100"),
        cost_basis=Decimal("9000"),
        current_price=Decimal("100"),
        currency="INR",
        sector="Equity: Flexi Cap",
        statement_date=date(2026, 7, 4),
        annual_dividend_per_share=Decimal("0"),
    )
    config = _config()
    config["base_currency"] = "USD"
    config["currency_conversion"] = {"rates_to_base": {"USD": 1, "INR": "0.0105"}}
    config["_fx_refresh"] = {
        "provider": "yahoo",
        "previous_rates_to_base": {"USD": Decimal("1"), "INR": Decimal("0.012")},
        "rates_to_base": {"USD": Decimal("1"), "INR": Decimal("0.0105")},
        "changed_currencies": ["INR"],
    }

    report = build_daily_report([holding], Decimal("120"), config)

    assert report["portfolio_value"] == Decimal("105.0000")
    assert report["daily_change"] == Decimal("-15.0000")
    assert report["fx_revaluation"]["fx_impact"] == Decimal("-15.0000")
    assert report["fx_revaluation"]["market_daily_change"] == Decimal("0.0000")

    html = write_html_report(report, tmp_path).read_text(encoding="utf-8")
    assert "Market Daily Change ($)" in html
    assert "FX Revaluation ($)" in html
    assert "Total Change After FX ($)" in html
    assert '<div class="value negative">-15.00</div>' in html
    assert '<div class="value negative">-15.00 (-12.50%)</div>' in html


def test_html_report_supports_common_output_currency_labels(tmp_path: Path) -> None:
    config = _config()
    config["base_currency"] = "USD"
    config["currency_conversion"] = {"rates_to_base": {"USD": 1, "EUR": "1.25", "GBP": "1.5", "JPY": "0.01"}}
    config["reporting"] = {"output_currency": "EUR"}

    report = build_daily_report(_holdings()[:1], None, config)
    html = write_html_report(report, tmp_path).read_text(encoding="utf-8")

    assert "Portfolio Value (€)" in html
    assert "Value (€)" in html
    assert "20,000.00" in html


def test_html_report_falls_back_to_base_currency_when_output_rate_is_missing(tmp_path: Path) -> None:
    config = _config()
    config["base_currency"] = "USD"
    config["currency_conversion"] = {"rates_to_base": {"USD": 1}}
    config["reporting"] = {"output_currency": "GBP"}

    report = build_daily_report(_holdings()[:1], None, config)
    html = write_html_report(report, tmp_path).read_text(encoding="utf-8")

    assert "Portfolio Value ($)" in html
    assert "Portfolio Value (£)" not in html


def test_report_accepts_fallback_flattened_currency_config() -> None:
    holding = Holding(
        account="Indian Mutual Funds",
        broker="Sift Capital",
        market="IN",
        symbol="MF_TEST",
        name="Example Indian MF",
        asset_type="Mutual Fund",
        quantity=Decimal("100"),
        cost_basis=Decimal("9000"),
        current_price=Decimal("100"),
        currency="INR",
        sector="Equity: Flexi Cap",
        statement_date=date(2026, 7, 4),
    )
    config = _config()
    config["base_currency"] = "USD"
    config["currency_conversion"] = {"rates_to_base": "", "USD": 1, "INR": "0.012"}

    report = build_daily_report([holding], None, config)

    assert report["portfolio_value"] == Decimal("120.000")


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
