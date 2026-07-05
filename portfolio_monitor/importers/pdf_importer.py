from __future__ import annotations

import csv
import re
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from portfolio_monitor.importers.csv_importer import load_csv
from portfolio_monitor.models import Holding, IncomeSummary


def load_pdf(path: Path) -> list[Holding]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("PDF import requires optional dependency: pip install '.[pdf]'") from exc

    text_pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_pages.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")

    full_text = "\n".join(text_pages)
    if "Crypto Statement" in full_text and "CRYPTOCURRENCY HELD IN ACCOUNT" in full_text:
        return _combine_holdings(_parse_robinhood_crypto(full_text))
    if "Securities Held in Account Sym/Cusip" in full_text:
        return _combine_holdings(_parse_robinhood_securities(full_text))
    if "INVESTMENT REPORT" in full_text and "Holdings" in full_text:
        fidelity_holdings = _parse_fidelity_holdings(full_text)
        fidelity_holdings.extend(_parse_fidelity_cash(full_text))
        if fidelity_holdings:
            return _combine_holdings(fidelity_holdings)
        return []

    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables.extend(page.extract_tables() or [])

    for table in tables:
        cleaned = [[cell or "" for cell in row] for row in table if row]
        if not cleaned:
            continue
        header = {str(cell).strip().lower() for cell in cleaned[0]}
        if {"symbol", "quantity", "statement_date"}.issubset(header):
            return _table_to_holdings(cleaned)

    raise ValueError(
        "Could not find a recognizable holdings table in the PDF. "
        "Export CSV/Excel from the broker or convert the statement table manually."
    )


def load_pdf_income_summaries(path: Path) -> list[IncomeSummary]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("PDF import requires optional dependency: pip install '.[pdf]'") from exc

    with pdfplumber.open(path) as pdf:
        full_text = "\n".join(page.extract_text(x_tolerance=1, y_tolerance=3) or "" for page in pdf.pages)

    summaries: list[IncomeSummary] = []
    if "INVESTMENT REPORT" in full_text:
        summary = _parse_fidelity_income(full_text)
        if summary:
            summaries.append(summary)
    if "Portfolio Allocation" in full_text and "Dividends" in full_text and "Robinhood" in full_text:
        summary = _parse_robinhood_income(full_text)
        if summary:
            summaries.append(summary)
    return summaries


def _table_to_holdings(table: list[list[str]]) -> list[Holding]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
        writer = csv.writer(handle)
        writer.writerows(table)
        temp_path = Path(handle.name)
    try:
        return load_csv(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _parse_robinhood_crypto(text: str) -> list[Holding]:
    statement_date = _parse_iso_date(_first_match(text, r"PERIOD END\s+(\d{4}-\d{2}-\d{2})")) or date.today()
    account = _first_match(text, r"RHS ACCOUNT NUMBER\s+(\S+)") or _first_match(text, r"ACCOUNT NUMBER\s+(\S+)") or "Robinhood Crypto"
    holdings: list[Holding] = []
    pattern = re.compile(
        r"^(?P<name>[A-Za-z][A-Za-z ]+?)\s+"
        r"(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<symbol>[A-Z0-9]+)\s+"
        r"\$(?P<market_value>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<pct>[\d.]+)%$"
    )
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        quantity = _to_decimal(match.group("quantity"))
        market_value = _to_decimal(match.group("market_value"))
        price = market_value / quantity if quantity else None
        holdings.append(
            Holding(
                account=account,
                broker="Robinhood",
                market="GLOBAL",
                symbol=match.group("symbol"),
                name=match.group("name").strip(),
                asset_type="Crypto",
                quantity=quantity,
                cost_basis=None,
                current_price=price,
                currency="USD",
                sector="Crypto",
                statement_date=statement_date,
                annual_dividend_per_share=Decimal("0"),
            )
        )
    return holdings


def _parse_robinhood_securities(text: str) -> list[Holding]:
    statement_date = _parse_robinhood_statement_end(text) or date.today()
    account = _first_match(text, r"Individual Account #:(\S+)") or "Robinhood"
    holdings: list[Holding] = []
    previous_line = ""
    pattern = re.compile(
        r"^(?P<symbol>[A-Z][A-Z0-9.]{0,12})\s+Cash\s+"
        r"(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
        r"\$(?P<price>[\d,]+(?:\.\d+)?)\s+"
        r"\$(?P<market_value>[\d,]+(?:\.\d+)?)\s+"
        r"\$(?P<dividend>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<pct>[\d.]+)%$"
    )
    for line in text.splitlines():
        clean = line.strip()
        match = pattern.match(clean)
        if match:
            quantity = _to_decimal(match.group("quantity"))
            estimated_dividend = _to_decimal(match.group("dividend"))
            holdings.append(
                Holding(
                    account=account,
                    broker="Robinhood",
                    market="US",
                    symbol=match.group("symbol"),
                    name=previous_line or match.group("symbol"),
                    asset_type="Stock",
                    quantity=quantity,
                    cost_basis=None,
                    current_price=_to_decimal(match.group("price")),
                    currency="USD",
                    sector=None,
                    statement_date=statement_date,
                    annual_dividend_per_share=(estimated_dividend / quantity) if quantity else None,
                )
            )
        if clean and not clean.startswith("Estimated Yield"):
            previous_line = clean
    return holdings


def _parse_fidelity_holdings(text: str) -> list[Holding]:
    statement_date = _parse_fidelity_statement_end(text) or date.today()
    account = _first_match(text, r"Account #\s+([A-Z0-9-]+)") or "Fidelity"
    holdings: list[Holding] = []
    section: str | None = None
    lines = [line.strip() for line in text.splitlines()]

    for index, line in enumerate(lines):
        if line == "Exchange Traded Products":
            section = "ETF"
            continue
        if line == "Stocks":
            section = "Stock"
            continue
        if line.startswith("Activity"):
            section = None
        if section is None or line.startswith("Total "):
            continue

        parsed = _parse_fidelity_position_line(line)
        if not parsed:
            continue
        description, quantity, price, _market_value, cost_basis, annual_income = parsed
        symbol = _extract_symbol_from_lines([line, *lines[index + 1 : index + 4]])
        if not symbol:
            continue
        holdings.append(
            Holding(
                account=account,
                broker="Fidelity",
                market="US",
                symbol=symbol,
                name=description,
                asset_type=section,
                quantity=quantity,
                cost_basis=cost_basis,
                current_price=price,
                currency="USD",
                sector=None,
                statement_date=statement_date,
                annual_dividend_per_share=(annual_income / quantity) if quantity else None,
            )
        )
    return holdings


def _parse_fidelity_cash(text: str) -> list[Holding]:
    statement_date = _parse_fidelity_statement_end(text) or date.today()
    account = _first_match(text, r"Account #\s+([A-Z0-9-]+)") or "Fidelity"
    holdings: list[Holding] = []
    pattern = re.compile(
        r"^CASH\s+\$?[\d,]+\.\d{2}\s+"
        r"(?P<quantity>[\d,]+(?:\.\d+)?)\s+"
        r"\$?1\.0000\s+"
        r"\$?(?P<market_value>[\d,]+\.\d{2})",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        quantity = _to_decimal(match.group("quantity"))
        market_value = _to_decimal(match.group("market_value"))
        holdings.append(
            Holding(
                account=account,
                broker="Fidelity",
                market="US",
                symbol="CASH",
                name="Core Cash / Free Credit Balance",
                asset_type="Cash",
                quantity=quantity,
                cost_basis=market_value,
                current_price=Decimal("1"),
                currency="USD",
                sector="Cash",
                statement_date=statement_date,
                annual_dividend_per_share=Decimal("0"),
            )
        )
    return holdings


def _parse_fidelity_income(text: str) -> IncomeSummary | None:
    statement_date = _parse_fidelity_statement_end(text) or date.today()
    account = _first_match(text, r"Account #\s+([A-Z0-9-]+)") or "Fidelity"
    dividend_match = re.search(r"^Dividends\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$", text, re.MULTILINE)
    interest_matches = re.findall(r"Interest\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text)
    total_income_match = re.search(r"Total Dividends, Interest & Other Income\s+\$?([\d,]+\.\d{2})", text)
    if not dividend_match and not interest_matches and not total_income_match:
        return None
    interest_period = _to_decimal(interest_matches[0][0]) if interest_matches else None
    interest_ytd = _to_decimal(interest_matches[0][1]) if interest_matches else None
    total_period = _to_decimal(total_income_match.group(1)) if total_income_match else None
    dividends_period = _to_decimal(dividend_match.group(1)) if dividend_match else None
    dividends_ytd = _to_decimal(dividend_match.group(2)) if dividend_match else None
    other_income_period = None
    if total_period is not None and dividends_period is None and interest_period is None:
        other_income_period = total_period
    return IncomeSummary(
        account=account,
        broker="Fidelity",
        statement_date=statement_date,
        dividends_period=dividends_period,
        dividends_ytd=dividends_ytd,
        interest_period=interest_period,
        interest_ytd=interest_ytd,
        other_income_period=other_income_period,
    )


def _parse_robinhood_income(text: str) -> IncomeSummary | None:
    statement_date = _parse_robinhood_statement_end(text) or date.today()
    account = _first_match(text, r"Individual Account #:(\S+)") or "Robinhood"
    dividends = re.search(r"Dividends\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})", text)
    interest = re.search(r"Interest Earned\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})", text)
    stock_lending = re.search(r"Stock Lending\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})", text)
    if not dividends and not interest and not stock_lending:
        return None
    return IncomeSummary(
        account=account,
        broker="Robinhood",
        statement_date=statement_date,
        dividends_period=_to_decimal(dividends.group(1)) if dividends else None,
        dividends_ytd=_to_decimal(dividends.group(2)) if dividends else None,
        interest_period=_to_decimal(interest.group(1)) if interest else None,
        interest_ytd=_to_decimal(interest.group(2)) if interest else None,
        other_income_period=_to_decimal(stock_lending.group(1)) if stock_lending else None,
        other_income_ytd=_to_decimal(stock_lending.group(2)) if stock_lending else None,
    )


def _parse_fidelity_position_line(line: str) -> tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal] | None:
    tokens = line.replace("$", "").split()
    if len(tokens) < 8:
        return None
    numeric = tokens[-7:]
    try:
        beginning_value = _to_decimal(numeric[0])
        quantity = _to_decimal(numeric[1])
        price = _to_decimal(numeric[2])
        market_value = _to_decimal(numeric[3])
        cost_basis = _to_decimal(numeric[4])
        _gain_loss = _to_decimal(numeric[5])
        annual_income = _to_decimal(numeric[6])
    except ValueError:
        return None
    if beginning_value < 0 or quantity <= 0 or market_value <= 0:
        return None
    description = " ".join(tokens[:-7]).strip()
    if not description:
        return None
    return description, quantity, price, market_value, cost_basis, annual_income


def _extract_symbol_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        match = re.search(r"\(([A-Z][A-Z0-9.]{0,12})\)", line)
        if match:
            return match.group(1)
    return None


def _parse_robinhood_statement_end(text: str) -> date | None:
    match = re.search(r"\b\d{2}/\d{2}/\d{4}\s+to\s+(\d{2})/(\d{2})/(\d{4})", text)
    if not match:
        return None
    month, day, year = match.groups()
    return date(int(year), int(month), int(day))


def _parse_fidelity_statement_end(text: str) -> date | None:
    match = re.search(r"[A-Za-z]+ \d{1,2}, \d{4}\s+-\s+([A-Za-z]+) (\d{1,2}), (\d{4})", text)
    if not match:
        return None
    month_name, day, year = match.groups()
    return date.fromisoformat(f"{year}-{_month_number(month_name):02d}-{int(day):02d}")


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _month_number(month_name: str) -> int:
    months = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    return months[month_name]


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _to_decimal(value: str) -> Decimal:
    normalized = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc


def _combine_holdings(holdings: list[Holding]) -> list[Holding]:
    combined: dict[tuple[str, str, str, str], Holding] = {}
    for holding in holdings:
        key = (holding.account, holding.broker, holding.market, holding.symbol)
        existing = combined.get(key)
        if existing is None:
            combined[key] = holding
            continue
        quantity = existing.quantity + holding.quantity
        market_value = existing.market_value + holding.market_value
        cost_basis = _add_optional(existing.cost_basis, holding.cost_basis)
        annual_dividend = _add_optional(
            _annual_dividend(existing),
            _annual_dividend(holding),
        )
        combined[key] = Holding(
            account=existing.account,
            broker=existing.broker,
            market=existing.market,
            symbol=existing.symbol,
            name=existing.name,
            asset_type=existing.asset_type,
            quantity=quantity,
            cost_basis=cost_basis,
            current_price=(market_value / quantity) if quantity else None,
            currency=existing.currency,
            sector=existing.sector,
            statement_date=max(existing.statement_date, holding.statement_date),
            annual_dividend_per_share=(annual_dividend / quantity) if annual_dividend is not None and quantity else None,
        )
    return list(combined.values())


def _add_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None and right is None:
        return None
    return (left or Decimal("0")) + (right or Decimal("0"))


def _annual_dividend(holding: Holding) -> Decimal | None:
    if holding.annual_dividend_per_share is None:
        return None
    return holding.annual_dividend_per_share * holding.quantity
