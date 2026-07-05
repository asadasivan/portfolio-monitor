from __future__ import annotations

from pathlib import Path

from portfolio_monitor.importers.csv_importer import load_csv
from portfolio_monitor.models import Holding


def load_holdings(path: str | Path) -> list[Holding]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return load_csv(file_path)
    if suffix in {".xlsx", ".xls"}:
        from portfolio_monitor.importers.excel_importer import load_excel

        return load_excel(file_path)
    if suffix == ".pdf":
        from portfolio_monitor.importers.pdf_importer import load_pdf

        return load_pdf(file_path)
    raise ValueError(f"Unsupported input type: {suffix}")
