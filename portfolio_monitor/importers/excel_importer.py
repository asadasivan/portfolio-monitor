from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from portfolio_monitor.importers.csv_importer import load_csv
from portfolio_monitor.models import Holding


def load_excel(path: Path) -> list[Holding]:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("Excel import requires optional dependency: pip install '.[excel]'") from exc

    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
        temp_path = Path(handle.name)
    try:
        return load_csv(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
