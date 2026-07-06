from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


def report_filename(report: dict[str, Any], suffix: str) -> str:
    report_type = report.get("report_type", "report")
    as_of = report.get("as_of", "latest")
    return f"{as_of}.{report_type}.{suffix}"


def write_latest_alias(path: Path, latest_name: str) -> None:
    latest = path.parent / latest_name
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value


def money(value: Any) -> str:
    if value is None:
        return "n/a"
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    return f"${decimal:,.2f}"


def pct(value: Any) -> str:
    if value is None:
        return "n/a"
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    return f"{decimal:.2f}%"
