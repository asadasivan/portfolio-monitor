from __future__ import annotations

import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.domain.models import Holding

SUPPORTED_FX_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "INR",
    "CAD",
    "AUD",
    "CHF",
    "CNY",
    "HKD",
    "SGD",
    "NZD",
    "SEK",
    "NOK",
    "KRW",
    "AED",
    "SAR",
    "ZAR",
    "BRL",
    "MXN",
}


@dataclass(frozen=True)
class PriceResult:
    symbol: str
    market: str
    current_price: Decimal | None
    provider_symbol: str
    status: str
    message: str | None = None


@dataclass(frozen=True)
class FxRateResult:
    currency: str
    base_currency: str
    rate_to_base: Decimal | None
    provider_symbol: str
    status: str
    message: str | None = None


def fetch_current_prices(holdings: list[Holding], provider: str) -> list[PriceResult]:
    cash_results = [
        PriceResult(
            symbol=holding.symbol,
            market=holding.market,
            current_price=Decimal("1"),
            provider_symbol="CASH",
            status="ok",
            message="Cash is valued at par.",
        )
        for holding in holdings
        if holding.normalized_asset_type == "cash"
    ]
    market_holdings = [holding for holding in holdings if holding.normalized_asset_type != "cash"]
    timeout_seconds = 6
    if ":" in provider:
        provider, timeout_text = provider.split(":", 1)
        timeout_seconds = int(timeout_text)
    provider_name = provider.lower()
    if provider_name == "yahoo":
        india_mfs, other_holdings = _split_indian_mutual_funds(market_holdings)
        return (
            cash_results
            + _fetch_yahoo_prices(other_holdings, timeout_seconds=timeout_seconds)
            + _fetch_amfi_prices(india_mfs, timeout_seconds=timeout_seconds)
        )
    if provider_name in {"yahoo-amfi", "hybrid"}:
        india_mfs, other_holdings = _split_indian_mutual_funds(market_holdings)
        return (
            cash_results
            + _fetch_yahoo_prices(other_holdings, timeout_seconds=timeout_seconds)
            + _fetch_amfi_prices(india_mfs, timeout_seconds=timeout_seconds)
        )
    if provider_name == "amfi":
        return cash_results + _fetch_amfi_prices(market_holdings, timeout_seconds=timeout_seconds)
    if provider_name == "yfinance":
        return cash_results + _fetch_yfinance_prices(market_holdings)
    raise ValueError(f"Unsupported online price provider: {provider}")


def fetch_fx_rates(base_currency: str, currencies: set[str], provider: str) -> list[FxRateResult]:
    timeout_seconds = 6
    if ":" in provider:
        provider, timeout_text = provider.split(":", 1)
        timeout_seconds = int(timeout_text)
    provider_name = provider.lower()
    if provider_name not in {"yahoo", "yahoo-amfi", "hybrid", "yfinance"}:
        raise ValueError(f"Unsupported online FX provider: {provider}")

    base = base_currency.upper()
    results: list[FxRateResult] = []
    for currency in sorted({item.upper() for item in currencies}):
        if currency == base:
            results.append(FxRateResult(currency, base, Decimal("1"), currency, "ok"))
            continue
        if currency not in SUPPORTED_FX_CURRENCIES:
            results.append(FxRateResult(currency, base, None, currency, "unsupported", "Currency is not in the supported FX list."))
            continue
        results.append(_fetch_yahoo_fx_rate(currency, base, timeout_seconds))
    return results


def provider_symbol(holding: Holding) -> str:
    symbol = holding.symbol.upper()
    market = holding.market.upper()
    asset_type = holding.normalized_asset_type

    if asset_type == "crypto" and "-" not in symbol:
        return f"{symbol}-USD"
    if market == "IN":
        if symbol.endswith(".NSE"):
            return f"{symbol.removesuffix('.NSE')}.NS"
        if symbol.endswith(".BSE"):
            return f"{symbol.removesuffix('.BSE')}.BO"
    return symbol


def _fetch_yahoo_fx_rate(currency: str, base_currency: str, timeout_seconds: int) -> FxRateResult:
    direct_symbol = f"{currency}{base_currency}=X"
    inverse_symbol = f"{base_currency}{currency}=X"
    try:
        direct_rate = _fetch_yahoo_price(direct_symbol, timeout_seconds=timeout_seconds)
        if direct_rate is not None:
            return FxRateResult(currency, base_currency, direct_rate, direct_symbol, "ok")
        inverse_rate = _fetch_yahoo_price(inverse_symbol, timeout_seconds=timeout_seconds)
        if inverse_rate is not None:
            return FxRateResult(currency, base_currency, Decimal("1") / inverse_rate, inverse_symbol, "ok")
        return FxRateResult(
            currency,
            base_currency,
            None,
            direct_symbol,
            "not_found",
            "Yahoo did not return a usable FX rate.",
        )
    except (HTTPError, URLError, TimeoutError, socket.timeout, OSError, json.JSONDecodeError) as exc:
        return FxRateResult(currency, base_currency, None, direct_symbol, "error", str(exc))


def _fetch_yahoo_prices(holdings: list[Holding], timeout_seconds: int) -> list[PriceResult]:
    results: list[PriceResult] = []
    for holding in holdings:
        mapped_symbol = provider_symbol(holding)
        try:
            price = _fetch_yahoo_price(mapped_symbol, timeout_seconds=timeout_seconds)
            if price is None:
                results.append(
                    PriceResult(
                        symbol=holding.symbol,
                        market=holding.market,
                        current_price=None,
                        provider_symbol=mapped_symbol,
                        status="not_found",
                        message="Yahoo did not return a usable regular market price.",
                    )
                )
            else:
                results.append(
                    PriceResult(
                        symbol=holding.symbol,
                        market=holding.market,
                        current_price=price,
                        provider_symbol=mapped_symbol,
                        status="ok",
                    )
                )
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError, json.JSONDecodeError) as exc:
            results.append(
                PriceResult(
                    symbol=holding.symbol,
                    market=holding.market,
                    current_price=None,
                    provider_symbol=mapped_symbol,
                    status="error",
                    message=str(exc),
                )
            )
    return results


def _split_indian_mutual_funds(holdings: list[Holding]) -> tuple[list[Holding], list[Holding]]:
    india_mfs: list[Holding] = []
    other_holdings: list[Holding] = []
    for holding in holdings:
        if holding.market.upper() == "IN" and holding.normalized_asset_type == "mutual fund":
            india_mfs.append(holding)
        else:
            other_holdings.append(holding)
    return india_mfs, other_holdings


def _fetch_amfi_prices(holdings: list[Holding], timeout_seconds: int) -> list[PriceResult]:
    if not holdings:
        return []
    try:
        nav_rows = _fetch_amfi_nav_rows(timeout_seconds)
    except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as exc:
        return [
            PriceResult(
                symbol=holding.symbol,
                market=holding.market,
                current_price=None,
                provider_symbol="AMFI",
                status="error",
                message=str(exc),
            )
            for holding in holdings
        ]

    return [_match_amfi_price(holding, nav_rows) for holding in holdings]


def _fetch_amfi_nav_rows(timeout_seconds: int) -> list[dict[str, str]]:
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    request = Request(url, headers={"User-Agent": "portfolio-monitor/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        text = response.read().decode("utf-8", errors="replace")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(";")]
        if len(parts) != 6 or parts[0] == "Scheme Code":
            continue
        price = _to_decimal(parts[4])
        if price is None:
            continue
        rows.append({"code": parts[0], "name": parts[3], "nav": parts[4], "date": parts[5]})
    return rows


def _match_amfi_price(holding: Holding, nav_rows: list[dict[str, str]]) -> PriceResult:
    holding_tokens = _scheme_tokens(holding.name)
    holding_core = _scheme_core(holding.name)
    best_row: dict[str, str] | None = None
    best_score = 0
    for row in nav_rows:
        nav_tokens = _scheme_tokens(row["name"])
        nav_core = _scheme_core(row["name"])
        if not holding_tokens:
            continue
        common = len(holding_tokens & nav_tokens)
        missing = len(holding_tokens - nav_tokens)
        score = common * 3 - missing * 2
        holding_is_regular = _is_regular_plan_name(holding.name)
        holding_is_growth = _is_growth_name(holding.name)
        nav_name = row["name"].lower()
        nav_price = _to_decimal(row["nav"])
        nav_is_direct = "direct" in nav_name
        nav_is_regular = "regular" in nav_name or re.search(r"\breg\b", nav_name) is not None
        nav_is_growth = "growth" in nav_name
        nav_is_distribution = "idcw" in nav_name or "bonus" in nav_name or "dividend" in nav_name
        if holding_core and holding_core in nav_core:
            score += 15
        elif common >= max(2, len(holding_tokens) - 1):
            score += 2
        else:
            continue
        if holding_is_regular and nav_is_direct:
            score -= 8
        if holding_is_regular and nav_is_regular:
            score += 3
        if holding_is_growth and nav_is_growth:
            score += 4
        if holding_is_growth and nav_is_distribution:
            score -= 6
        if holding.current_price and nav_price:
            relative_diff = abs(nav_price - holding.current_price) / holding.current_price
            score -= int(relative_diff * 100)
        if score > best_score:
            best_row = row
            best_score = score

    if not best_row:
        return PriceResult(
            symbol=holding.symbol,
            market=holding.market,
            current_price=None,
            provider_symbol="AMFI",
            status="not_found",
            message=f"AMFI did not find a close scheme match for {holding.name}.",
        )

    return PriceResult(
        symbol=holding.symbol,
        market=holding.market,
        current_price=_to_decimal(best_row["nav"]),
        provider_symbol=f"AMFI:{best_row['code']}",
        status="ok",
        message=best_row["name"],
    )


def _scheme_tokens(name: str) -> set[str]:
    tokens = set(_scheme_core(name).split())
    stop_words = {
        "fund",
        "plan",
        "option",
        "regular",
        "reg",
        "direct",
        "idcw",
        "bonus",
        "dividend",
        "the",
        "and",
        "of",
    }
    return tokens - stop_words


def _scheme_core(name: str) -> str:
    normalized = name.lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"\blargecap\b", "large cap", normalized)
    normalized = re.sub(r"\bmidcap\b", "mid cap", normalized)
    normalized = re.sub(r"\bsmallcap\b", "small cap", normalized)
    normalized = re.sub(r"\bflexicap\b", "flexi cap", normalized)
    normalized = re.sub(r"\bmulticap\b", "multi cap", normalized)
    normalized = re.sub(r"\(g\)", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _is_regular_plan_name(name: str) -> bool:
    normalized = name.lower()
    return " reg " in f" {normalized} " or "regular" in normalized


def _is_growth_name(name: str) -> bool:
    normalized = name.lower()
    return "(g)" in normalized or "growth" in normalized


def _fetch_yahoo_price(symbol: str, timeout_seconds: int) -> Decimal | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range=1d&interval=1d"
    request = Request(url, headers={"User-Agent": "portfolio-monitor/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    for field in ("regularMarketPrice", "previousClose", "chartPreviousClose"):
        price = _to_decimal(meta.get(field))
        if price is not None:
            return price
    close_values = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    for value in reversed(close_values):
        price = _to_decimal(value)
        if price is not None:
            return price
    return None


def _fetch_yfinance_prices(holdings: list[Holding]) -> list[PriceResult]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Online price refresh requires optional dependency: pip install '.[market]'") from exc

    results: list[PriceResult] = []
    for holding in holdings:
        mapped_symbol = provider_symbol(holding)
        try:
            ticker = yf.Ticker(mapped_symbol)
            price = _extract_yfinance_price(ticker)
            if price is None:
                results.append(
                    PriceResult(
                        symbol=holding.symbol,
                        market=holding.market,
                        current_price=None,
                        provider_symbol=mapped_symbol,
                        status="not_found",
                        message="Provider did not return a usable current price.",
                    )
                )
            else:
                results.append(
                    PriceResult(
                        symbol=holding.symbol,
                        market=holding.market,
                        current_price=price,
                        provider_symbol=mapped_symbol,
                        status="ok",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - keep one failed ticker from breaking the full loop.
            results.append(
                PriceResult(
                    symbol=holding.symbol,
                    market=holding.market,
                    current_price=None,
                    provider_symbol=mapped_symbol,
                    status="error",
                    message=str(exc),
                )
            )
    return results


def _extract_yfinance_price(ticker: object) -> Decimal | None:
    fast_info = getattr(ticker, "fast_info", None)
    for field in ("last_price", "regular_market_price", "previous_close"):
        price = _read_field(fast_info, field)
        if price is not None:
            return price

    info = getattr(ticker, "info", {}) or {}
    for field in ("regularMarketPrice", "currentPrice", "previousClose"):
        price = _to_decimal(info.get(field))
        if price is not None:
            return price
    return None


def _read_field(source: object, field: str) -> Decimal | None:
    if source is None:
        return None
    try:
        value = source[field]  # type: ignore[index]
    except (KeyError, TypeError):
        value = getattr(source, field, None)
    return _to_decimal(value)


def _to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if decimal <= 0:
        return None
    return decimal
