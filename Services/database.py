"""Versioned database initialization and consistent SQLite backups."""

import math
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("APOTHICAIRE_DB", BASE_DIR / "data" / "portfolio.db"))
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
_lock = threading.RLock()
_ready = set()


class ManagedConnection(sqlite3.Connection):
    """Commit/rollback and close deterministically, including on Windows."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _open(path):
    return sqlite3.connect(path, timeout=30, factory=ManagedConnection)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def backup_database(path=None):
    path = Path(path or DB_PATH)
    if not path.exists():
        return None
    folder = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"portfolio-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.db"
    with _open(path) as source, _open(target) as destination:
        source.backup(destination)
    return target


def initialize_database(path=None):
    path = Path(path or DB_PATH)
    key = str(path.resolve())
    with _lock:
        if key in _ready and path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy = BASE_DIR / "portfolio.db"
        if (
            not path.exists()
            and path == DB_PATH
            and not os.environ.get("APOTHICAIRE_DB")
            and legacy.exists()
        ):
            with _open(legacy) as source, _open(path) as destination:
                source.backup(destination)
        with _open(path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio'"
            ).fetchone()
        if version < 1:
            if existing:
                backup_database(path)
            with _open(path) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN IMMEDIATE")
                # Another worker may have migrated while we waited for the lock.
                if conn.execute("PRAGMA user_version").fetchone()[0] >= 1:
                    conn.commit()
                    return initialize_database(path)
                old = (
                    [dict(row) for row in conn.execute("SELECT * FROM portfolio")]
                    if existing
                    else []
                )
                grouped = {}
                for row in old:
                    ticker = str(row.get("ticker") or "").strip().upper()
                    if not ticker:
                        raise ValueError(
                            "Migration stopped: a holding has no ticker. Original database is preserved."
                        )
                    shares, cost, price = (
                        float(row.get(k) or 0) for k in ("shares", "avg_price", "current_price")
                    )
                    if not all(math.isfinite(x) and x >= 0 for x in (shares, cost, price)):
                        raise ValueError(f"Migration stopped: invalid numbers for {ticker}.")
                    g = grouped.setdefault(
                        ticker,
                        dict(shares=0.0, cost=0.0, price=0.0, quote_at=None, type="Unassigned"),
                    )
                    g["shares"] += shares
                    g["cost"] += shares * cost
                    stamp = row.get("quote_updated_at") or row.get("last_updated")
                    if price > 0 and (
                        g["quote_at"] is None or str(stamp or "") >= str(g["quote_at"])
                    ):
                        g.update(price=price, quote_at=stamp)
                    if row.get("holding_type"):
                        g["type"] = row["holding_type"]
                if existing:
                    conn.execute("ALTER TABLE portfolio RENAME TO portfolio_legacy")
                for statement in (BASE_DIR / "schema.sql").read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        conn.execute(statement)
                now = utc_now()
                for ticker, g in grouped.items():
                    if g["shares"] <= 0:
                        continue
                    avg = g["cost"] / g["shares"]
                    price = g["price"] or avg
                    conn.execute(
                        "INSERT INTO portfolio(ticker,shares,avg_price,current_price,market_value,Total_Profit_Loss,holding_type,last_updated,quote_updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            ticker,
                            g["shares"],
                            avg,
                            g["price"],
                            price * g["shares"],
                            (price - avg) * g["shares"],
                            g["type"],
                            now,
                            g["quote_at"],
                        ),
                    )
                    conn.execute(
                        "INSERT INTO transactions(timestamp,kind,ticker,shares,price,note) VALUES(?,?,?,?,?,?)",
                        (
                            now,
                            "opening",
                            ticker,
                            g["shares"],
                            avg,
                            "Imported current position; earlier trading history is unknown.",
                        ),
                    )
                value = sum(
                    (g["price"] or (g["cost"] / g["shares"] if g["shares"] else 0)) * g["shares"]
                    for g in grouped.values()
                )
                conn.execute(
                    "INSERT INTO valuations(timestamp,nav,external_flow) VALUES(?,?,0)",
                    (now, value),
                )
                conn.execute("PRAGMA user_version=1")
                conn.commit()
        if version < 2:
            if version == 1:
                backup_database(path)
            with _open(path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                columns = {row[1] for row in conn.execute("PRAGMA table_info(portfolio)")}
                if "quote_checked_at" not in columns:
                    conn.execute("ALTER TABLE portfolio ADD COLUMN quote_checked_at TEXT")
                conn.execute("PRAGMA user_version=2")
        _ready.add(key)
    return path


def connect(path=None):
    conn = _open(initialize_database(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_engine():
    initialize_database()
    return create_engine(DATABASE_URL, connect_args={"timeout": 30})
