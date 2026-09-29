"""Atomic trades, cash movements and observed account performance."""

import math
import re

import pandas as pd

from Services.database import connect, utc_now

HOLDING_TYPES = ("Core", "High Conviction", "Moonshot", "Unassigned")


def number(value, label, positive=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Enter a valid {label}.") from None
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(
            f"{label.capitalize()} must be {'positive' if positive else 'nonnegative'}."
        )
    return result


def cash_balance(conn):
    return float(conn.execute("SELECT COALESCE(SUM(amount),0) FROM transactions").fetchone()[0])


def record_valuation(conn, external_flow=0):
    holdings = float(
        conn.execute("SELECT COALESCE(SUM(market_value),0) FROM portfolio").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO valuations(timestamp,nav,external_flow) VALUES(?,?,?)",
        (utc_now(), holdings + cash_balance(conn), external_flow),
    )


def transact(
    kind,
    ticker=None,
    shares=None,
    price=None,
    holding_type=None,
    amount=None,
    fees=0,
    note="",
    path=None,
):
    if kind not in ("buy", "sell", "deposit", "withdrawal", "dividend", "fee"):
        raise ValueError("Unknown transaction type.")
    ticker = str(ticker or "").strip().upper()
    fees = number(fees or 0, "fees")
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        record_valuation(conn)
        now = utc_now()
        qty = execution = realized = flow = 0.0
        if kind in ("buy", "sell"):
            if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,24}", ticker):
                raise ValueError("Enter a valid ticker.")
            qty, execution = number(shares, "shares", True), number(price, "execution price", True)
            row = conn.execute("SELECT * FROM portfolio WHERE ticker=?", (ticker,)).fetchone()
            current_qty = row["shares"] if row else 0.0
            avg = row["avg_price"] if row else 0.0
            if kind == "buy":
                if holding_type not in HOLDING_TYPES:
                    raise ValueError("Select a valid holding type.")
                change = -(qty * execution + fees)
                if cash_balance(conn) + change < -1e-8:
                    raise ValueError("Insufficient recorded cash. Record a deposit before buying.")
                new_qty = current_qty + qty
                avg = (current_qty * avg + qty * execution + fees) / new_qty
                quote = row["current_price"] if row and row["current_price"] else execution
                if row:
                    conn.execute(
                        "UPDATE portfolio SET shares=?,avg_price=?,market_value=?,Total_Profit_Loss=?,holding_type=?,last_updated=? WHERE ticker=?",
                        (
                            new_qty,
                            avg,
                            new_qty * quote,
                            (quote - avg) * new_qty,
                            holding_type,
                            now,
                            ticker,
                        ),
                    )
                else:
                    conn.execute(
                        "INSERT INTO portfolio(ticker,shares,avg_price,current_price,market_value,Total_Profit_Loss,holding_type,last_updated) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            ticker,
                            new_qty,
                            avg,
                            execution,
                            new_qty * execution,
                            (execution - avg) * new_qty,
                            holding_type,
                            now,
                        ),
                    )
            else:
                if not row or qty > current_qty + 1e-10:
                    raise ValueError(f"Cannot sell {qty:g} shares; you hold {current_qty:g}.")
                change = qty * execution - fees
                if cash_balance(conn) + change < -1e-8:
                    raise ValueError("Insufficient cash to cover sale fees.")
                realized = (execution - avg) * qty - fees
                new_qty = max(current_qty - qty, 0.0)
                quote = row["current_price"] or avg
                if new_qty <= 1e-10:
                    conn.execute("DELETE FROM portfolio WHERE ticker=?", (ticker,))
                else:
                    conn.execute(
                        "UPDATE portfolio SET shares=?,market_value=?,Total_Profit_Loss=?,last_updated=? WHERE ticker=?",
                        (new_qty, new_qty * quote, (quote - avg) * new_qty, now, ticker),
                    )
        else:
            if fees:
                raise ValueError("Record cash-event fees separately as a Fee transaction.")
            change = number(amount, "amount", True) * (-1 if kind in ("withdrawal", "fee") else 1)
            if cash_balance(conn) + change < -1e-8:
                raise ValueError("Insufficient recorded cash.")
            flow = change if kind in ("deposit", "withdrawal") else 0.0
        conn.execute(
            "INSERT INTO transactions(timestamp,kind,ticker,shares,price,amount,fees,realized_pnl,note) VALUES(?,?,?,?,?,?,?,?,?)",
            (now, kind, ticker or None, qty, execution, change, fees, realized, str(note or "")),
        )
        record_valuation(conn, flow)
    return f"Recorded {kind}" + (
        f": {qty:g} {ticker} at ${execution:,.2f}." if qty else f": ${abs(change):,.2f}."
    )


def set_holding_type(ticker, holding_type, path=None):
    if holding_type not in HOLDING_TYPES:
        raise ValueError("Select a valid holding type.")
    with connect(path) as conn:
        result = conn.execute(
            "UPDATE portfolio SET holding_type=?,last_updated=? WHERE ticker=?",
            (holding_type, utc_now(), str(ticker or "").strip().upper()),
        )
        if result.rowcount != 1:
            raise ValueError("Ticker not found.")
    return "Holding type updated."


def account_summary(path=None):
    with connect(path) as conn:
        cash = cash_balance(conn)
        row = conn.execute(
            "SELECT COALESCE(SUM(market_value),0),COALESCE(SUM(Total_Profit_Loss),0) FROM portfolio"
        ).fetchone()
        realized = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0) FROM transactions"
        ).fetchone()[0]
    return dict(cash=cash, holdings=row[0], nav=cash + row[0], unrealized=row[1], realized=realized)


def transaction_history(path=None):
    with connect(path) as conn:
        return pd.read_sql_query("SELECT * FROM transactions ORDER BY id DESC", conn)


def account_performance(path=None):
    with connect(path) as conn:
        values = pd.read_sql_query("SELECT * FROM valuations ORDER BY id", conn)
    if values.empty:
        return values
    previous = values.nav.shift(1)
    values["return"] = ((values.nav - values.external_flow) / previous - 1).where(previous > 0, 0.0)
    values["growth"] = (1 + values["return"]).cumprod()
    return values
