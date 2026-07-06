from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Holding:
    account: str
    broker: str
    market: str
    symbol: str
    name: str
    asset_type: str
    quantity: Decimal
    cost_basis: Decimal | None
    current_price: Decimal | None
    currency: str
    sector: str | None
    statement_date: date
    annual_dividend_per_share: Decimal | None = None

    @property
    def market_value(self) -> Decimal:
        if self.current_price is None:
            return Decimal("0")
        return self.quantity * self.current_price

    @property
    def normalized_asset_type(self) -> str:
        return self.asset_type.strip().lower()


@dataclass(frozen=True)
class IncomeSummary:
    account: str
    broker: str
    statement_date: date
    dividends_period: Decimal | None = None
    dividends_ytd: Decimal | None = None
    interest_period: Decimal | None = None
    interest_ytd: Decimal | None = None
    other_income_period: Decimal | None = None
    other_income_ytd: Decimal | None = None


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    code: str
    message: str
    remediation: str
    symbol: str | None = None
    account: str | None = None
