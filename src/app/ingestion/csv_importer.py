from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.domain.models import Holding

REQUIRED_FIELDS = {
    "account",
    "broker",
    "market",
    "symbol",
    "name",
    "asset_type",
    "quantity",
    "currency",
    "statement_date",
}


def load_csv(path: Path) -> list[Holding]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} does not contain a header row")
        normalized_fields = {field.strip() for field in reader.fieldnames}
        missing = REQUIRED_FIELDS - normalized_fields
        if missing:
            raise ValueError(f"{path} is missing required fields: {sorted(missing)}")
        return [_row_to_holding(row) for row in reader if any(row.values())]


def _row_to_holding(row: dict[str, str]) -> Holding:
    clean = {key.strip(): (value or "").strip() for key, value in row.items()}
    return Holding(
        account=clean["account"],
        broker=clean["broker"],
        market=clean["market"].upper(),
        symbol=clean["symbol"].upper(),
        name=clean["name"],
        asset_type=clean["asset_type"],
        quantity=_decimal(clean["quantity"], required=True),
        cost_basis=_decimal(clean.get("cost_basis", "")),
        current_price=_decimal(clean.get("current_price", "")),
        currency=(clean.get("currency") or "USD").upper(),
        sector=clean.get("sector") or None,
        statement_date=date.fromisoformat(clean["statement_date"]),
        annual_dividend_per_share=_decimal(clean.get("annual_dividend_per_share", "")),
    )


def _decimal(value: str | None, required: bool = False) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValueError("Required decimal field is empty")
        return None
    normalized = value.replace(",", "").replace("$", "").replace("₹", "")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc
