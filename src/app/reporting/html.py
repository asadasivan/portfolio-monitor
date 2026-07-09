from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any

from app.reporting.serialization import report_filename, write_latest_alias


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _number(value: Any) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return "n/a"
    return f"{decimal:,.2f}"


def _rates_to_base(report: dict[str, Any]) -> dict[str, Decimal]:
    conversion = report.get("currency_conversion", {})
    rates = conversion.get("rates_to_base", {}) if isinstance(conversion, dict) else {}
    if not isinstance(rates, dict):
        return {str(report.get("base_currency", "USD")).upper(): Decimal("1")}
    return {str(currency).upper(): Decimal(str(rate)) for currency, rate in rates.items()}


def _base_currency(report: dict[str, Any]) -> str:
    return str(report.get("base_currency", "USD")).upper()


def _output_currency(report: dict[str, Any]) -> str:
    requested = str(report.get("output_currency") or _base_currency(report)).upper()
    base_currency = _base_currency(report)
    if requested == base_currency or requested in _rates_to_base(report):
        return requested
    return base_currency


def _currency_symbol(currency: str) -> str:
    return {"USD": "$", "INR": "INR"}.get(currency.upper(), currency.upper())


def _currency_heading(label: str, report: dict[str, Any]) -> str:
    return f"{label} ({_currency_symbol(_output_currency(report))})"


def _display_money(value: Any, report: dict[str, Any]) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return "n/a"
    output_currency = _output_currency(report)
    base_currency = _base_currency(report)
    if output_currency == base_currency:
        return f"{decimal:,.2f}"
    rate = _rates_to_base(report).get(output_currency)
    if rate is None or rate == 0:
        return f"{decimal:,.2f}"
    return f"{(decimal / rate):,.2f}"


def _money_with_native(
    value: Any,
    report: dict[str, Any],
    native_value: Any = None,
    native_currency: Any = None,
) -> str:
    text = _display_money(value, report)
    native_decimal = _decimal(native_value)
    if native_decimal is None or not native_currency or str(native_currency).upper() == _output_currency(report):
        return text
    return f"{text} ({escape(str(native_currency))} {native_decimal:,.2f})"


def _pct(value: Any) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return "n/a"
    return f"{decimal:.2f}%"


def _signed_class(value: Any) -> str:
    decimal = _decimal(value)
    if decimal is None or decimal == 0:
        return ""
    return "positive" if decimal > 0 else "negative"


def _negative_row_class(*values: Any) -> str:
    for value in values:
        decimal = _decimal(value)
        if decimal is not None and decimal < 0:
            return "negative-row"
    return ""


def _risk_class(status: Any) -> str:
    text = str(status or "").upper()
    if "BREACH" in text:
        return "risk-breach"
    if "WATCH" in text or "REVIEW" in text or "WARNING" in text:
        return "risk-watch"
    return "risk-ok"


def _status_class(status: Any) -> str:
    text = str(status or "").lower().replace("_", "-").replace(" ", "-")
    return text or "unknown"


def _status_badge(status: Any) -> str:
    text = str(status or "UNKNOWN")
    return f'<span class="recon-status status-{escape(_status_class(text))}">{escape(text)}</span>'


def _td(value: Any, class_name: str = "", raw: bool = False) -> str:
    class_attr = f' class="{class_name}"' if class_name else ""
    content = str(value) if raw else escape(str(value))
    return f"<td{class_attr}>{content}</td>"


def _th(value: str) -> str:
    return f"<th>{escape(value)}</th>"


def _simple_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(_th(header) for header in headers)
    body = "".join("<tr>" + "".join(_td(value) for value in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _reconciliation_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(_th(header) for header in headers)
    body_rows = []
    status_index = len(headers) - 1
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            if index == status_index:
                cells.append(_td(_status_badge(value), "recon-status-cell", raw=True))
            else:
                cells.append(_td(value))
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _summary(report: dict[str, Any]) -> str:
    holdings_count = len(report.get("holdings", []))
    generated = datetime.now().isoformat(timespec="seconds")
    daily_change = report.get("daily_change")
    daily_change_pct = report.get("daily_change_pct")
    cards = [
        ("As of", report.get("as_of", "n/a")),
        (_currency_heading("Portfolio Value", report), _display_money(report.get("portfolio_value"), report)),
        (_currency_heading("Daily Change", report), f"{_display_money(daily_change, report)} ({_pct(daily_change_pct)})"),
        ("Holdings", holdings_count),
    ]
    return (
        f'<div class="generated muted">Generated {escape(generated)}</div>'
        '<section class="summary-grid">'
        + "".join(
            f'<div class="card"><div class="label">{escape(str(label))}</div>'
            f'<div class="value">{escape(str(value))}</div></div>'
            for label, value in cards
        )
        + "</section>"
    )


def _severity_counts(quality: dict[str, Any]) -> str:
    counts = quality.get("by_severity", {})
    if not counts:
        return "No issues"
    labels = {
        "critical": "Critical",
        "warning": "Needs review",
        "info": "Missing optional data",
    }
    parts = []
    for label in ["critical", "warning", "info"]:
        count = counts.get(label, 0)
        parts.append(f'<span class="mini-stat {escape(label)}">{escape(labels[label])}: {escape(str(count))}</span>')
    return "".join(parts)


def _issue_severity_label(severity: Any) -> str:
    labels = {
        "critical": "Critical",
        "warning": "Needs review",
        "info": "Missing optional data",
    }
    return labels.get(str(severity or "").lower(), "Review")


def _report_checks(report: dict[str, Any]) -> str:
    reconciliation = report.get("account_reconciliation", [])
    stale_account_values = report.get("stale_account_values", [])
    broker_total_requests = report.get("broker_total_requests", [])
    broker_check_mode = report.get("broker_check_mode", "current_price")
    quality = report.get("quality", {})
    issues = quality.get("issues", [])
    quality_status = str(quality.get("status", "UNKNOWN"))

    if reconciliation:
        matched = sum(1 for item in reconciliation if str(item.get("status", "")).upper() == "MATCHED")
        recon_status = "MATCHED" if matched == len(reconciliation) else "REVIEW"
        if broker_check_mode == "statement_import":
            recon_detail = f"{matched}/{len(reconciliation)} accounts matched after new statement import"
        else:
            recon_detail = f"{matched}/{len(reconciliation)} accounts matched"
        recon_table = _reconciliation_table(
            [
                "Account",
                _currency_heading("Reported", report),
                _currency_heading("Parsed", report),
                _currency_heading("Diff", report),
                "Status",
            ],
            [
                [
                    item.get("account", ""),
                    _display_money(item.get("reported_value"), report),
                    _display_money(item.get("parsed_holdings_value"), report),
                    _display_money(item.get("difference"), report),
                    item.get("status", ""),
                ]
                for item in reconciliation
            ],
        )
        recon_details = (
            f'<details><summary>View reconciliation</summary>'
            f'<div class="details-table-wrap">{recon_table}</div></details>'
        )
    elif broker_total_requests:
        recon_status = "NEEDED"
        recon_detail = "Current broker totals are needed before reconciliation can run for newly imported statements."
        request_table = _simple_table(
            ["Account", "Statement As Of", "Required As Of", "Reason"],
            [
                [
                    item.get("account", ""),
                    item.get("statement_as_of", ""),
                    item.get("required_as_of", ""),
                    item.get("reason", ""),
                ]
                for item in broker_total_requests
            ],
        )
        recon_details = (
            f'<details><summary>View needed broker totals</summary>'
            f'<div class="details-table-wrap">{request_table}</div></details>'
        )
    elif stale_account_values:
        has_missing = any(str(item.get("status", "")).upper() == "MISSING_CURRENT_TOTAL" for item in stale_account_values)
        recon_status = "NEEDED" if has_missing else "SKIPPED"
        recon_detail = "Broker totals are missing or older than this current-price report, so reconciliation was skipped."
        stale_table = _reconciliation_table(
            ["Account", _currency_heading("Reported", report), "Broker As Of", "Report As Of", "Status"],
            [
                [
                    item.get("account", ""),
                    _display_money(item.get("reported_value"), report),
                    item.get("as_of", ""),
                    item.get("report_as_of", ""),
                    item.get("status", ""),
                ]
                for item in stale_account_values
            ],
        )
        recon_details = (
            f'<details><summary>View broker totals</summary>'
            f'<div class="details-table-wrap">{stale_table}</div></details>'
        )
    else:
        recon_status = "NOT SET"
        recon_detail = "No Fidelity/Robinhood app totals were entered for comparison."
        recon_details = ""

    if issues:
        issue_items = ""
        for issue in issues:
            severity = str(issue.get("severity", "warning")).lower()
            label = _issue_severity_label(severity)
            subject = issue.get("symbol") or issue.get("account") or issue.get("code") or "Item"
            issue_items += (
                f'<li class="issue-item severity-{escape(severity)}">'
                f'<span class="issue-tag {escape(severity)}">{escape(label)}</span>'
                f'<span><strong>{escape(str(subject))}</strong> {escape(str(issue.get("message", "")))}</span>'
                "</li>"
            )
        issue_details = f'<details><summary>View all issues</summary><ul class="issue-list">{issue_items}</ul></details>'
    else:
        issue_details = ""

    return f"""
<section class="checks-section">
  <div class="section-heading">
    <h2>Report Checks</h2>
    <span class="muted">Quick checks before relying on the numbers</span>
  </div>
  <div class="checks-grid">
    <div class="check-card">
      <div class="check-label">Broker total check</div>
      <div class="check-main"><span class="status-pill {escape(recon_status.lower().replace(' ', '-'))}">{escape(recon_status)}</span></div>
      <p>{escape(recon_detail)}</p>
      {recon_details}
    </div>
    <div class="check-card">
      <div class="check-label">Data quality</div>
      <div class="check-main"><span class="status-pill {escape(quality_status.lower())}">{escape(quality_status)}</span></div>
      <div class="mini-stats">{_severity_counts(quality)}</div>
      {issue_details}
    </div>
    <div class="check-card">
      <div class="check-label">Price freshness</div>
      <div class="check-main"><span class="status-pill stored">Stored prices</span></div>
      <p>Values use imported or last refreshed prices.</p>
    </div>
  </div>
</section>"""


def _account_breakdown(report: dict[str, Any]) -> str:
    rows = [[account, _display_money(value, report)] for account, value in sorted(report.get("by_account", {}).items())]
    return (
        f'<section class="section-account"><h2>Account Breakdown</h2>'
        f'{_simple_table(["Account", _currency_heading("Value", report)], rows)}</section>'
    )


def _asset_breakdown(report: dict[str, Any]) -> str:
    rows = [[asset_type, _display_money(value, report)] for asset_type, value in sorted(report.get("by_asset_type", {}).items())]
    return (
        f'<section class="section-asset"><h2>Asset-Type Breakdown</h2>'
        f'{_simple_table(["Category", _currency_heading("Value", report)], rows)}</section>'
    )


def _risk_alerts(report: dict[str, Any]) -> str:
    alerts = report.get("concentration_alerts", [])
    if not alerts:
        items = "<li>No risk alerts detected.</li>"
    else:
        items = "".join(f"<li>{escape(str(alert))}</li>" for alert in alerts)
    return f'<section class="section-risk"><h2>Risk Alerts</h2><ul>{items}</ul></section>'


def _holding_row(holding: dict[str, Any], report: dict[str, Any]) -> str:
    gain_loss = holding.get("gain_loss")
    gain_loss_pct = holding.get("gain_loss_pct")
    row_class = _negative_row_class(gain_loss, gain_loss_pct)
    class_attr = f' class="{row_class}"' if row_class else ""
    return (
        f"<tr{class_attr}>"
        + _td(holding.get("account", ""))
        + _td(holding.get("asset_type", ""))
        + _td(holding.get("symbol", ""))
        + _td(_number(holding.get("quantity")))
        + _td(_money_with_native(holding.get("price"), report, holding.get("native_price"), holding.get("currency")))
        + _td(
            _money_with_native(
                holding.get("market_value"),
                report,
                holding.get("native_market_value"),
                holding.get("currency"),
            )
        )
        + _td(_money_with_native(holding.get("cost_basis"), report, holding.get("native_cost_basis"), holding.get("currency")))
        + _td(
            _money_with_native(gain_loss, report, holding.get("native_gain_loss"), holding.get("currency")),
            _signed_class(gain_loss),
        )
        + _td(_pct(gain_loss_pct), _signed_class(gain_loss_pct))
        + _td(_pct(holding.get("portfolio_pct")))
        + _td(_display_money(holding.get("annual_dividend"), report))
        + "</tr>"
    )


def _sum_optional(holdings: list[dict[str, Any]], field: str) -> Decimal | None:
    values = [_decimal(holding.get(field)) for holding in holdings]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present, Decimal("0"))


def _single_native_currency(holdings: list[dict[str, Any]]) -> str | None:
    currencies = {
        str(holding.get("currency"))
        for holding in holdings
        if holding.get("native_market_value") is not None and holding.get("currency")
    }
    if len(currencies) == 1:
        return next(iter(currencies))
    return None


def _holding_total_row(holdings: list[dict[str, Any]], report: dict[str, Any]) -> str:
    market_value = _sum_optional(holdings, "market_value")
    cost_basis = _sum_optional(holdings, "cost_basis")
    gain_loss = _sum_optional(holdings, "gain_loss")
    gain_loss_pct = (gain_loss / cost_basis) * Decimal("100") if gain_loss is not None and cost_basis else None
    portfolio_pct = _sum_optional(holdings, "portfolio_pct")
    annual_dividend = _sum_optional(holdings, "annual_dividend")
    native_currency = _single_native_currency(holdings)
    native_market_value = _sum_optional(holdings, "native_market_value") if native_currency else None
    native_cost_basis = _sum_optional(holdings, "native_cost_basis") if native_currency else None
    native_gain_loss = _sum_optional(holdings, "native_gain_loss") if native_currency else None
    row_class = "total-row"
    if _negative_row_class(gain_loss):
        row_class += " negative-row"
    return (
        f'<tr class="{row_class}">'
        + _td("Total")
        + _td("")
        + _td("")
        + _td("")
        + _td("")
        + _td(_money_with_native(market_value, report, native_market_value, native_currency))
        + _td(_money_with_native(cost_basis, report, native_cost_basis, native_currency))
        + _td(_money_with_native(gain_loss, report, native_gain_loss, native_currency), _signed_class(gain_loss))
        + _td(_pct(gain_loss_pct), _signed_class(gain_loss_pct))
        + _td(_pct(portfolio_pct))
        + _td(_display_money(annual_dividend, report))
        + "</tr>"
    )


def _holding_table_section(title: str, holdings: list[dict[str, Any]], report: dict[str, Any]) -> str:
    rows = [_holding_row(holding, report) for holding in holdings]
    if not rows:
        rows = ['<tr><td colspan="11" class="muted">No holdings in this category.</td></tr>']
    else:
        rows.append(_holding_total_row(holdings, report))
    headers = [
        "Account",
        "Type",
        "Symbol",
        "Units",
        _currency_heading("Last Price", report),
        _currency_heading("Market Value", report),
        _currency_heading("Cost Basis", report),
        _currency_heading("Total Gain/Loss", report),
        "Gain/Loss %",
        "Portfolio %",
        _currency_heading("Est. Annual Dividend", report),
    ]
    return (
        f'<section class="section-holdings"><h2>{escape(title)}</h2><table data-interactive="true"><thead><tr>'
        + "".join(_th(header) for header in headers)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></section>"
    )


def _holdings_tables(report: dict[str, Any]) -> str:
    holdings = list(report.get("holdings", []))
    us_stock_etf = [
        holding
        for holding in holdings
        if holding.get("market") == "US" and holding.get("asset_type") in {"Stock", "ETF"}
    ]
    india_mf_stock = [
        holding
        for holding in holdings
        if holding.get("market") == "IN" and holding.get("asset_type") in {"MF", "Stock"}
    ]
    crypto = [holding for holding in holdings if holding.get("asset_type") == "Crypto"]
    categorized = {id(holding) for holding in [*us_stock_etf, *india_mf_stock, *crypto]}
    other = [holding for holding in holdings if id(holding) not in categorized]
    sections = [
        _holding_table_section("US Stocks and ETF", us_stock_etf, report),
        _holding_table_section("India MF and Stocks", india_mf_stock, report),
        _holding_table_section("Crypto", crypto, report),
    ]
    if other:
        sections.append(_holding_table_section("Other Holdings", other, report))
    return "".join(sections)


def _risk_by_holding_table(report: dict[str, Any]) -> str:
    rows = []
    for holding in report.get("holdings", []):
        status = holding.get("risk_status", "")
        rows.append(
            "<tr>"
            + _td(holding.get("account", ""))
            + _td(holding.get("asset_type", ""))
            + _td(holding.get("symbol", ""))
            + _td(_pct(holding.get("portfolio_pct")))
            + _td(status, _risk_class(status))
            + "</tr>"
        )
    return (
        "<section class=\"section-risk-table\"><h2>Risk By Holding</h2><table data-interactive='true'><thead><tr>"
        + "".join(_th(header) for header in ["Account", "Type", "Symbol", "Portfolio %", "Status"])
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></section>"
    )


def _dividend_estimate(report: dict[str, Any]) -> str:
    dividends = report.get("dividends", {})
    return (
        '<section class="section-dividend"><h2>Dividend Estimate</h2>'
        f"<p><strong>{escape(_currency_heading('Projected annual dividend', report))}:</strong> "
        f"{escape(_display_money(dividends.get('projected_annual'), report))}</p>"
        f"<p><strong>{escape(_currency_heading('Projected monthly average', report))}:</strong> "
        f"{escape(_display_money(dividends.get('projected_monthly_average'), report))}</p>"
        "<p>Basis: statement-provided estimated annual income where available. This is an estimate, not a guaranteed dividend forecast.</p>"
        "</section>"
    )


def _script() -> str:
    return """
  <script>
    (() => {
      const parseValue = (text) => {
        const normalized = text.replace(/[$,%]/g, "").replace(/,/g, "").replace(/−/g, "-").trim();
        if (!normalized || normalized.toLowerCase() === "n/a") return null;
        const numeric = Number(normalized);
        return Number.isFinite(numeric) ? numeric : text.toLowerCase();
      };

      const cellText = (row, index) => (row.cells[index]?.textContent || "").trim();

      const filterTable = (table, searchInput, rowCount) => {
        const search = searchInput.value.trim().toLowerCase();
        const rows = Array.from(table.tBodies[0]?.rows || []);
        let visible = 0;
        for (const row of rows) {
          const matchesSearch = !search || row.textContent.toLowerCase().includes(search);
          row.style.display = matchesSearch ? "" : "none";
          if (matchesSearch) visible += 1;
        }
        rowCount.textContent = `${visible} / ${rows.length} rows`;
      };

      const setColumnVisible = (table, columnIndex, visible) => {
        const display = visible ? "" : "none";
        Array.from(table.rows).forEach((row) => {
          if (row.cells[columnIndex]) row.cells[columnIndex].style.display = display;
        });
      };

      const sortTable = (table, columnIndex, direction, headers) => {
        const tbody = table.tBodies[0];
        if (!tbody) return;
        headers.forEach((item) => {
          item.classList.remove("sort-asc", "sort-desc");
          delete item.dataset.sortDirection;
        });
        const header = headers[columnIndex];
        if (header) {
          header.dataset.sortDirection = direction;
          header.classList.add(direction === "asc" ? "sort-asc" : "sort-desc");
        }
        const rows = Array.from(tbody.rows);
        rows.sort((left, right) => {
          const leftValue = parseValue(cellText(left, columnIndex));
          const rightValue = parseValue(cellText(right, columnIndex));
          if (leftValue === null && rightValue === null) return 0;
          if (leftValue === null) return 1;
          if (rightValue === null) return -1;
          if (typeof leftValue === "number" && typeof rightValue === "number") {
            return direction === "asc" ? leftValue - rightValue : rightValue - leftValue;
          }
          return direction === "asc"
            ? String(leftValue).localeCompare(String(rightValue))
            : String(rightValue).localeCompare(String(leftValue));
        });
        rows.forEach((row) => tbody.appendChild(row));
      };

      const enhanceTable = (table, index) => {
        if (!table.tHead || !table.tBodies.length) return;
        const headers = Array.from(table.tHead.rows[0].cells);
        const tbody = table.tBodies[0];
        const originalRows = Array.from(tbody.rows);
        if (!headers.length) return;

        const tools = document.createElement("div");
        tools.className = "table-tools";
        tools.dataset.tableIndex = String(index);
        const primaryTools = document.createElement("div");
        primaryTools.className = "table-tools-primary";
        const secondaryTools = document.createElement("div");
        secondaryTools.className = "table-tools-secondary";

        const searchInput = document.createElement("input");
        searchInput.type = "search";
        searchInput.placeholder = "Search table";
        searchInput.setAttribute("aria-label", "Search this table");

        const columnPicker = document.createElement("details");
        columnPicker.className = "column-picker";
        const columnSummary = document.createElement("summary");
        columnSummary.textContent = "Filter";
        columnSummary.title = "Choose visible columns";
        columnSummary.setAttribute("aria-label", "Choose visible columns");
        const columnOptions = document.createElement("div");
        columnOptions.className = "column-options";
        columnPicker.append(columnSummary, columnOptions);
        headers.forEach((header, headerIndex) => {
          const label = document.createElement("label");
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.checked = true;
          checkbox.dataset.columnIndex = String(headerIndex);
          checkbox.addEventListener("change", () => {
            setColumnVisible(table, headerIndex, checkbox.checked);
          });
          label.append(checkbox, header.textContent.trim() || `Column ${headerIndex + 1}`);
          columnOptions.appendChild(label);
        });
        const columnActions = document.createElement("div");
        columnActions.className = "column-picker-actions";
        const closeColumnsButton = document.createElement("button");
        closeColumnsButton.type = "button";
        closeColumnsButton.textContent = "Close";
        closeColumnsButton.addEventListener("click", () => {
          columnPicker.open = false;
        });
        columnActions.appendChild(closeColumnsButton);
        columnOptions.appendChild(columnActions);

        const resetButton = document.createElement("button");
        resetButton.type = "button";
        resetButton.className = "reset-button";
        resetButton.textContent = "Reset";

        const rowCount = document.createElement("div");
        rowCount.className = "row-count";

        primaryTools.append(columnPicker, searchInput);
        secondaryTools.append(resetButton, rowCount);
        tools.append(primaryTools, secondaryTools);
        table.before(tools);

        const applyFilters = () => filterTable(table, searchInput, rowCount);
        searchInput.addEventListener("input", applyFilters);
        document.addEventListener("click", (event) => {
          if (columnPicker.open && !columnPicker.contains(event.target)) {
            columnPicker.open = false;
          }
        });
        columnPicker.addEventListener("keydown", (event) => {
          if (event.key === "Escape") {
            columnPicker.open = false;
            columnSummary.focus();
          }
        });
        resetButton.addEventListener("click", () => {
          searchInput.value = "";
          headers.forEach((header) => {
            header.classList.remove("sort-asc", "sort-desc");
            delete header.dataset.sortDirection;
          });
          Array.from(columnOptions.querySelectorAll("input[type='checkbox']")).forEach((checkbox) => {
            checkbox.checked = true;
            setColumnVisible(table, Number(checkbox.dataset.columnIndex), true);
          });
          columnPicker.open = false;
          originalRows.forEach((row) => tbody.appendChild(row));
          applyFilters();
        });

        headers.forEach((header, headerIndex) => {
          header.classList.add("sortable");
          header.title = "Click to sort";
          header.addEventListener("click", () => {
            const next = header.dataset.sortDirection === "asc" ? "desc" : "asc";
            sortTable(table, headerIndex, next, headers);
            applyFilters();
          });
        });
        applyFilters();
      };

      document.querySelectorAll("table[data-interactive='true']").forEach(enhanceTable);
    })();
  </script>"""


def write_html_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    title = f"Portfolio {str(report.get('report_type', 'report')).title()} Report"
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #5f6b7a;
      --border: #d9dee7;
      --header: #203040;
      --brand: #1d4ed8;
      --brand-soft: #dbeafe;
      --good: #0f766e;
      --bad: #b42318;
      --watch: #a16207;
      --soft: #eef2f7;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px 24px 56px;
    }}
    h1 {{
      margin: 0 0 20px;
      color: var(--brand);
      font-size: 30px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 14px;
      color: var(--section-color, var(--header));
      font-size: 20px;
    }}
    .section-holdings h2,
    .section-risk-table h2 {{
      color: #0f3f66;
    }}
    .generated {{
      margin: -12px 0 18px;
      font-size: 13px;
    }}
    section {{
      --section-color: var(--header);
      background: var(--panel);
      border: 1px solid var(--border);
      border-top: 4px solid var(--section-color);
      border-radius: 8px;
      margin: 18px 0;
      padding: 18px;
      overflow-x: auto;
    }}
    .summary-grid {{
      --section-color: transparent;
    }}
    .checks-section {{ --section-color: #2563eb; }}
    .section-account {{ --section-color: #0f766e; }}
    .section-asset {{ --section-color: #7c3aed; }}
    .section-risk,
    .section-risk-table {{ --section-color: #b45309; }}
    .section-holdings {{ --section-color: #0369a1; }}
    .section-dividend {{ --section-color: #047857; }}
    .section-disclaimer {{ --section-color: #64748b; }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
      background: transparent;
      border: 0;
      padding: 0;
      overflow: visible;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-top: 3px solid var(--brand-soft);
      border-radius: 8px;
      padding: 14px;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .value {{
      margin-top: 6px;
      font-size: 18px;
      font-weight: 650;
    }}
    .checks-section {{
      overflow: visible;
    }}
    .section-heading {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .section-heading h2 {{
      margin: 0;
    }}
    .checks-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .check-card {{
      border: 1px solid var(--border);
      border-left: 4px solid var(--section-color);
      border-radius: 8px;
      background: #fbfcfe;
      padding: 12px;
      min-height: 116px;
      min-width: 0;
      overflow: hidden;
    }}
    .check-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .check-main {{
      margin-top: 8px;
    }}
    .check-card p {{
      color: var(--muted);
      font-size: 13px;
      margin: 10px 0 0;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 9px;
      background: var(--soft);
      color: var(--header);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .02em;
      text-transform: uppercase;
    }}
    .status-pill.ok,
    .status-pill.matched {{
      background: #dcfce7;
      color: var(--good);
    }}
    .status-pill.watch,
    .status-pill.review,
    .status-pill.not-set,
    .status-pill.not-configured,
    .status-pill.stored {{
      background: #fef3c7;
      color: var(--watch);
    }}
    .status-pill.review_required,
    .status-pill.critical {{
      background: #fee2e2;
      color: var(--bad);
    }}
    .mini-stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }}
    .mini-stat {{
      border-radius: 999px;
      background: #eef2f7;
      color: var(--muted);
      font-size: 12px;
      padding: 3px 7px;
    }}
    .mini-stat.critical {{
      background: #fee2e2;
      color: var(--bad);
    }}
    .mini-stat.warning {{
      background: #fef3c7;
      color: var(--watch);
    }}
    .mini-stat.info {{
      background: #e0f2fe;
      color: #0369a1;
    }}
    .issue-list {{
      display: grid;
      gap: 6px;
      list-style: none;
      margin: 10px 0 0;
      padding: 0;
    }}
    .issue-item {{
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      border-top: 1px solid var(--border);
      padding: 8px 0 2px;
    }}
    .issue-tag {{
      border-radius: 999px;
      padding: 2px 7px;
      font-size: 11px;
      font-weight: 750;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .issue-tag.critical {{
      background: #fee2e2;
      color: var(--bad);
    }}
    .issue-tag.warning {{
      background: #fef3c7;
      color: var(--watch);
    }}
    .issue-tag.info {{
      background: #e0f2fe;
      color: #0369a1;
    }}
    details {{
      margin-top: 10px;
      font-size: 13px;
      max-width: 100%;
    }}
    details summary {{
      color: var(--header);
      cursor: pointer;
      font-weight: 650;
    }}
    details table {{
      margin-top: 0;
      font-size: 13px;
    }}
    .details-table-wrap {{
      max-width: 100%;
      margin-top: 10px;
      overflow-x: auto;
      overscroll-behavior-x: contain;
    }}
    .details-table-wrap table {{
      width: max-content;
      min-width: 100%;
    }}
    .recon-status-cell {{
      text-align: left;
    }}
    .recon-status {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 70px;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .02em;
      line-height: 1.2;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .recon-status.status-matched,
    .recon-status.status-ok {{
      background: #dcfce7;
      color: var(--good);
    }}
    .recon-status.status-watch,
    .recon-status.status-review,
    .recon-status.status-needed,
    .recon-status.status-skipped,
    .recon-status.status-missing-current-total {{
      background: #fef3c7;
      color: var(--watch);
    }}
    .recon-status.status-critical,
    .recon-status.status-error,
    .recon-status.status-failed,
    .recon-status.status-mismatch {{
      background: #fee2e2;
      color: var(--bad);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      white-space: nowrap;
    }}
    .table-tools {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin: 2px 0 14px;
      padding: 0;
      background: transparent;
    }}
    .table-tools-primary,
    .table-tools-secondary {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      height: 38px;
      min-width: 0;
    }}
    .table-tools input[type="search"] {{
      display: block;
      width: clamp(260px, 32vw, 430px);
      flex: 0 1 auto;
      margin: 0;
      line-height: 38px;
    }}
    .table-tools input,
    .table-tools select {{
      height: 38px;
      box-sizing: border-box;
      border: 1px solid #d5dce6;
      border-radius: 999px;
      background: #ffffff;
      color: var(--text);
      padding: 0 16px;
      font: inherit;
      font-size: 14px;
      line-height: 1;
      margin: 0;
      box-shadow: 0 1px 3px rgba(15, 23, 42, .04);
    }}
    .table-tools input[type="search"]::placeholder {{
      color: #9aa8b7;
    }}
    .table-tools button,
    .column-picker summary {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 38px;
      min-width: 86px;
      box-sizing: border-box;
      border: 1px solid #d5dce6;
      border-radius: 999px;
      background: #ffffff;
      color: #111827;
      padding: 0 16px;
      font: inherit;
      font-size: 14px;
      font-weight: 800;
      line-height: 1;
      margin: 0;
      cursor: pointer;
      white-space: nowrap;
      box-shadow: 0 1px 3px rgba(15, 23, 42, .05);
    }}
    .table-tools button:hover,
    .column-picker summary:hover {{
      border-color: #b8c7d9;
      background: #f8fafc;
    }}
    .table-tools button:focus-visible,
    .column-picker summary:focus-visible,
    .table-tools input:focus-visible {{
      outline: 2px solid #60a5fa;
      outline-offset: 1px;
    }}
    .table-tools .reset-button {{
      align-self: center;
      width: 86px;
      min-width: 86px;
      color: #496273;
    }}
    .column-picker summary {{
      width: 86px;
      min-width: 86px;
      color: #496273;
    }}
    .column-picker {{
      display: flex;
      align-items: center;
      position: relative;
      height: 38px;
      margin: 0;
      padding: 0;
    }}
    .column-picker summary {{
      min-height: 38px;
      list-style: none;
      margin: 0;
      appearance: none;
      -webkit-appearance: none;
    }}
    .column-picker summary::-webkit-details-marker {{ display: none; }}
    .column-picker summary::after {{
      content: " ▾";
      color: var(--muted);
      margin-left: 6px;
      font-weight: 700;
    }}
    .column-picker[open] summary::after {{ content: " ▴"; }}
    .column-options {{
      position: absolute;
      z-index: 20;
      top: 44px;
      left: 0;
      min-width: 210px;
      max-height: 184px;
      overflow-y: auto;
      border: 1px solid #c8d4e2;
      border-radius: 10px;
      background: #ffffff;
      box-shadow: 0 12px 28px rgba(23, 32, 42, .16);
      padding: 4px;
    }}
    .column-options label {{
      display: flex;
      align-items: center;
      min-height: 24px;
      gap: 6px;
      padding: 2px 5px;
      color: var(--text);
      font-size: 12px;
      line-height: 1.2;
      white-space: nowrap;
    }}
    .column-options input {{
      width: 14px;
      height: 14px;
      flex: 0 0 auto;
      margin: 0;
      min-height: auto;
      padding: 0;
    }}
    .column-picker-actions {{
      display: flex;
      justify-content: flex-end;
      border-top: 1px solid var(--border);
      margin-top: 2px;
      padding-top: 4px;
    }}
    .column-picker-actions button {{
      height: 26px;
      min-width: 72px;
      padding: 0 10px;
      font-size: 12px;
    }}
    .table-tools .row-count {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 9px 10px;
      text-align: right;
    }}
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2),
    th:nth-child(3), td:nth-child(3) {{
      text-align: left;
    }}
    th {{
      background: #eaf2fb;
      color: #0f3f66;
      font-weight: 750;
    }}
    th.sortable {{
      cursor: pointer;
      user-select: none;
    }}
    th.sortable::after {{
      content: " ↕";
      color: var(--muted);
      font-weight: 500;
    }}
    th.sort-asc::after {{
      content: " ↑";
      color: var(--header);
    }}
    th.sort-desc::after {{
      content: " ↓";
      color: var(--header);
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .total-row td {{
      border-top: 2px solid var(--header);
      font-weight: 750;
      background: #f8fafc;
    }}
    .positive {{ color: var(--good); }}
    .negative {{ color: var(--bad); }}
    .negative-row td {{ color: var(--bad); }}
    .risk-breach {{ color: var(--bad); font-weight: 650; }}
    .risk-watch {{ color: var(--watch); font-weight: 650; }}
    .risk-ok {{ color: var(--muted); }}
    .muted {{ color: var(--muted); }}
    code {{
      background: var(--soft);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 4px;
    }}
    ul {{ margin: 0; padding-left: 20px; }}
    p {{ margin: 8px 0; }}
    @media (max-width: 800px) {{
      main {{ padding: 20px 12px 36px; }}
      .summary-grid {{ grid-template-columns: 1fr 1fr; }}
      .checks-grid {{ grid-template-columns: 1fr; }}
      .section-heading {{ align-items: flex-start; flex-direction: column; }}
      .table-tools {{ align-items: flex-start; flex-direction: column; }}
      .table-tools-primary {{ flex-wrap: wrap; width: 100%; }}
      .table-tools-secondary {{ justify-content: space-between; width: 100%; }}
      .table-tools input[type="search"] {{ flex: 1 1 220px; width: auto; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(title)}</h1>
    {_summary(report)}
    {_report_checks(report)}
    {_account_breakdown(report)}
    {_asset_breakdown(report)}
    {_risk_alerts(report)}
    {_holdings_tables(report)}
    {_risk_by_holding_table(report)}
    {_dividend_estimate(report)}
    <section class="section-disclaimer">
      <h2>Disclaimer</h2>
      <p>This report is educational decision support. It is not financial, tax, legal, or trading advice.</p>
    </section>
  </main>
  {_script()}
</body>
</html>
"""
    path = report_dir / report_filename(report, "html")
    path.write_text(html, encoding="utf-8")
    write_latest_alias(path, "latest.html")
    return path
