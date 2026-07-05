from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from portfolio_monitor.models import Holding, IncomeSummary


class PortfolioStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            create table if not exists holdings (
              id integer primary key,
              account text not null,
              broker text not null,
              market text not null,
              symbol text not null,
              name text not null,
              asset_type text not null,
              quantity text not null,
              cost_basis text,
              current_price text,
              currency text not null,
              sector text,
              statement_date text not null,
              annual_dividend_per_share text,
              status text not null default 'active',
              updated_at text not null,
              unique(account, broker, market, symbol)
            );

            create table if not exists statement_imports (
              id integer primary key,
              source text not null,
              imported_at text not null,
              holdings_count integer not null
            );

            create table if not exists daily_snapshots (
              id integer primary key,
              snapshot_date text not null unique,
              total_value text not null,
              created_at text not null
            );

            create table if not exists account_values (
              id integer primary key,
              account_label text not null unique,
              current_value text not null,
              currency text not null default 'USD',
              as_of text not null,
              updated_at text not null
            );

            create table if not exists income_summaries (
              id integer primary key,
              account text not null,
              broker text not null,
              statement_date text not null,
              dividends_period text,
              dividends_ytd text,
              interest_period text,
              interest_ytd text,
              other_income_period text,
              other_income_ytd text,
              updated_at text not null,
              unique(account, broker, statement_date)
            );
            """
        )
        self.connection.commit()

    def upsert_holdings(self, holdings: Iterable[Holding], source: str) -> dict[str, int]:
        now = datetime.utcnow().isoformat(timespec="seconds")
        holdings_list = list(holdings)
        touched_keys = {(h.account, h.broker, h.market, h.symbol) for h in holdings_list}
        touched_scopes = {(h.account, h.broker, h.market) for h in holdings_list}
        counts = {"inserted_or_updated": 0, "marked_missing": 0}

        with self.connection:
            for holding in holdings_list:
                cursor = self.connection.execute(
                    """
                    insert into holdings (
                      account, broker, market, symbol, name, asset_type, quantity,
                      cost_basis, current_price, currency, sector, statement_date,
                      annual_dividend_per_share, status, updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    on conflict(account, broker, market, symbol) do update set
                      name=excluded.name,
                      asset_type=excluded.asset_type,
                      quantity=excluded.quantity,
                      cost_basis=excluded.cost_basis,
                      current_price=excluded.current_price,
                      currency=excluded.currency,
                      sector=excluded.sector,
                      statement_date=excluded.statement_date,
                      annual_dividend_per_share=excluded.annual_dividend_per_share,
                      status='active',
                      updated_at=excluded.updated_at
                    where date(excluded.statement_date) >= date(holdings.statement_date)
                    """,
                    _holding_values(holding, now),
                )
                counts["inserted_or_updated"] += cursor.rowcount

            if source.lower() != "partial":
                active_rows = self.connection.execute(
                    "select account, broker, market, symbol from holdings where status = 'active'"
                ).fetchall()
                for row in active_rows:
                    scope = (row["account"], row["broker"], row["market"])
                    key = (*scope, row["symbol"])
                    if scope in touched_scopes and key not in touched_keys:
                        self.connection.execute(
                            """
                            update holdings
                            set status = 'missing_in_latest_statement', updated_at = ?
                            where account = ? and broker = ? and market = ? and symbol = ?
                            """,
                            (now, *key),
                        )
                        counts["marked_missing"] += 1

            self.connection.execute(
                "insert into statement_imports(source, imported_at, holdings_count) values (?, ?, ?)",
                (source, now, len(holdings_list)),
            )
        return counts

    def active_holdings(self) -> list[Holding]:
        rows = self.connection.execute(
            """
            select * from holdings
            where status = 'active'
            order by account, market, symbol
            """
        ).fetchall()
        return [_row_to_holding(row) for row in rows]

    def update_prices(self, prices: Iterable[dict[str, str]]) -> dict[str, int]:
        now = datetime.utcnow().isoformat(timespec="seconds")
        counts = {"updated": 0, "not_found": 0}
        with self.connection:
            for price in prices:
                symbol = price["symbol"].upper()
                market = price.get("market", "").upper()
                current_price = str(Decimal(str(price["current_price"])))
                if market:
                    cursor = self.connection.execute(
                        """
                        update holdings
                        set current_price = ?, updated_at = ?
                        where symbol = ? and market = ?
                        """,
                        (current_price, now, symbol, market),
                    )
                else:
                    cursor = self.connection.execute(
                        """
                        update holdings
                        set current_price = ?, updated_at = ?
                        where symbol = ?
                        """,
                        (current_price, now, symbol),
                    )
                if cursor.rowcount:
                    counts["updated"] += cursor.rowcount
                else:
                    counts["not_found"] += 1
        return counts

    def update_cost_basis(self, rows: Iterable[dict[str, str]]) -> dict[str, int]:
        now = datetime.utcnow().isoformat(timespec="seconds")
        counts = {"updated": 0, "not_found": 0, "skipped": 0}
        with self.connection:
            for row in rows:
                symbol = row["symbol"].upper()
                market = row.get("market", "").upper()
                broker = row.get("broker", "")
                cost_basis_text = row.get("cost_basis", "").strip()
                average_cost_text = row.get("average_cost", "").strip()
                if not cost_basis_text and not average_cost_text:
                    counts["skipped"] += 1
                    continue

                holding_rows = self._matching_active_holding_rows(symbol, market, broker)
                if not holding_rows:
                    counts["not_found"] += 1
                    continue

                for holding_row in holding_rows:
                    if average_cost_text:
                        cost_basis = Decimal(average_cost_text.replace(",", "")) * Decimal(holding_row["quantity"])
                    else:
                        cost_basis = Decimal(cost_basis_text.replace(",", ""))
                    self.connection.execute(
                        """
                        update holdings
                        set cost_basis = ?, updated_at = ?
                        where id = ?
                        """,
                        (str(cost_basis), now, holding_row["id"]),
                    )
                    counts["updated"] += 1
        return counts

    def _matching_active_holding_rows(self, symbol: str, market: str, broker: str) -> list[sqlite3.Row]:
        clauses = ["status = 'active'", "symbol = ?"]
        params: list[str] = [symbol]
        if market:
            clauses.append("market = ?")
            params.append(market)
        if broker:
            clauses.append("broker = ?")
            params.append(broker)
        return self.connection.execute(
            f"select id, quantity from holdings where {' and '.join(clauses)}",
            params,
        ).fetchall()

    def all_holdings_rows(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "select * from holdings order by status, account, market, symbol"
        ).fetchall()

    def upsert_account_value(
        self,
        account_label: str,
        current_value: Decimal,
        as_of: date,
        currency: str = "USD",
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                insert into account_values(account_label, current_value, currency, as_of, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(account_label) do update set
                  current_value=excluded.current_value,
                  currency=excluded.currency,
                  as_of=excluded.as_of,
                  updated_at=excluded.updated_at
                """,
                (account_label, str(current_value), currency, as_of.isoformat(), now),
            )

    def latest_account_values(self) -> dict[str, Decimal]:
        rows = self.connection.execute(
            "select account_label, current_value from account_values order by account_label"
        ).fetchall()
        return {row["account_label"]: Decimal(row["current_value"]) for row in rows}

    def upsert_income_summaries(self, summaries: Iterable[IncomeSummary]) -> int:
        now = datetime.utcnow().isoformat(timespec="seconds")
        count = 0
        with self.connection:
            for summary in summaries:
                cursor = self.connection.execute(
                    """
                    insert into income_summaries (
                      account, broker, statement_date, dividends_period, dividends_ytd,
                      interest_period, interest_ytd, other_income_period, other_income_ytd, updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(account, broker, statement_date) do update set
                      dividends_period=excluded.dividends_period,
                      dividends_ytd=excluded.dividends_ytd,
                      interest_period=excluded.interest_period,
                      interest_ytd=excluded.interest_ytd,
                      other_income_period=excluded.other_income_period,
                      other_income_ytd=excluded.other_income_ytd,
                      updated_at=excluded.updated_at
                    """,
                    _income_values(summary, now),
                )
                count += cursor.rowcount
        return count

    def latest_income_summaries(self) -> list[IncomeSummary]:
        rows = self.connection.execute(
            """
            select *
            from income_summaries
            where (broker, statement_date) in (
              select broker, max(statement_date)
              from income_summaries
              group by broker
            )
            order by broker, account
            """
        ).fetchall()
        return [_row_to_income(row) for row in rows]

    def latest_snapshot(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "select * from daily_snapshots order by snapshot_date desc limit 1"
        ).fetchone()

    def save_snapshot(self, snapshot_date: date, total_value: Decimal) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                insert into daily_snapshots(snapshot_date, total_value, created_at)
                values (?, ?, ?)
                on conflict(snapshot_date) do update set
                  total_value=excluded.total_value,
                  created_at=excluded.created_at
                """,
                (snapshot_date.isoformat(), str(total_value), now),
            )


def _holding_values(holding: Holding, now: str) -> tuple[str, ...]:
    return (
        holding.account,
        holding.broker,
        holding.market,
        holding.symbol,
        holding.name,
        holding.asset_type,
        str(holding.quantity),
        _decimal_to_text(holding.cost_basis),
        _decimal_to_text(holding.current_price),
        holding.currency,
        holding.sector,
        holding.statement_date.isoformat(),
        _decimal_to_text(holding.annual_dividend_per_share),
        now,
    )


def _income_values(summary: IncomeSummary, now: str) -> tuple[str | None, ...]:
    return (
        summary.account,
        summary.broker,
        summary.statement_date.isoformat(),
        _decimal_to_text(summary.dividends_period),
        _decimal_to_text(summary.dividends_ytd),
        _decimal_to_text(summary.interest_period),
        _decimal_to_text(summary.interest_ytd),
        _decimal_to_text(summary.other_income_period),
        _decimal_to_text(summary.other_income_ytd),
        now,
    )


def _row_to_holding(row: sqlite3.Row) -> Holding:
    return Holding(
        account=row["account"],
        broker=row["broker"],
        market=row["market"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        quantity=Decimal(row["quantity"]),
        cost_basis=_text_to_decimal(row["cost_basis"]),
        current_price=_text_to_decimal(row["current_price"]),
        currency=row["currency"],
        sector=row["sector"],
        statement_date=date.fromisoformat(row["statement_date"]),
        annual_dividend_per_share=_text_to_decimal(row["annual_dividend_per_share"]),
    )


def _row_to_income(row: sqlite3.Row) -> IncomeSummary:
    return IncomeSummary(
        account=row["account"],
        broker=row["broker"],
        statement_date=date.fromisoformat(row["statement_date"]),
        dividends_period=_text_to_decimal(row["dividends_period"]),
        dividends_ytd=_text_to_decimal(row["dividends_ytd"]),
        interest_period=_text_to_decimal(row["interest_period"]),
        interest_ytd=_text_to_decimal(row["interest_ytd"]),
        other_income_period=_text_to_decimal(row["other_income_period"]),
        other_income_ytd=_text_to_decimal(row["other_income_ytd"]),
    )


def _decimal_to_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _text_to_decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None
