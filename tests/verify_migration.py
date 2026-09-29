"""Verify opening shares and cost against the preserved legacy database."""

import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv()
from Services.database import BASE_DIR, ManagedConnection, backup_database, connect


def main():
    original = BASE_DIR / "portfolio.db"
    with sqlite3.connect(
        f"file:{original.as_posix()}?mode=ro", uri=True, factory=ManagedConnection
    ) as conn:
        original_rows = conn.execute("SELECT ticker,shares,avg_price FROM portfolio").fetchall()
    expected = {}
    for ticker, shares, cost in original_rows:
        ticker = str(ticker or "").strip().upper()
        quantity, basis = expected.get(ticker, (0.0, 0.0))
        expected[ticker] = (
            quantity + float(shares or 0),
            basis + float(shares or 0) * float(cost or 0),
        )
    expected = {ticker: values for ticker, values in expected.items() if values[0] > 0}
    with connect() as conn:
        actual = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT ticker,SUM(shares),SUM(shares*price) FROM transactions WHERE kind='opening' GROUP BY ticker"
            )
        }
        assert expected.keys() == actual.keys(), "Opening ticker mismatch"
        for ticker, (quantity, basis) in expected.items():
            assert math.isclose(quantity, actual[ticker][0], abs_tol=1e-8), (
                f"Share mismatch for {ticker}"
            )
            assert math.isclose(basis, actual[ticker][1], abs_tol=1e-6), (
                f"Cost-basis mismatch for {ticker}"
            )
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    backup = backup_database()
    print(
        f"Verified {len(expected)} opening positions: shares and cost basis match the preserved original. Database integrity OK. Backup: {backup.name}"
    )


if __name__ == "__main__":
    main()
