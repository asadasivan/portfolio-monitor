from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from portfolio_monitor.models import Holding


@dataclass(frozen=True)
class PriceResult:
    symbol: str
    market: str
    current_price: Decimal | None
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
        return cash_results + _fetch_yahoo_prices(market_holdings, timeout_seconds=timeout_seconds)
    if provider_name == "yfinance":
        return cash_results + _fetch_yfinance_prices(market_holdings)
    raise ValueError(f"Unsupported online price provider: {provider}")


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
