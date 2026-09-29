"""Batch quotes outside the write transaction; keep quote timestamps distinct."""

import logging

import numpy as np
import pandas as pd
import yfinance as yf

from Services.database import connect
from Services.helper import load_data
from Services.ledger import record_valuation

LOG = logging.getLogger(__name__)


def update_prices(force=False):
    holdings = load_data()
    if holdings.empty:
        return "No holdings to refresh."
    now = pd.Timestamp.now(tz="UTC")
    stamps = pd.to_datetime(holdings.quote_checked_at, utc=True, errors="coerce")
    stale = (
        holdings if force else holdings[(now - stamps > pd.Timedelta(minutes=15)) | stamps.isna()]
    )
    tickers = stale.ticker.tolist()
    if not tickers:
        return "Quotes were checked within the last 15 minutes."
    try:
        data = yf.download(
            tickers=tickers,
            period="5d",
            interval="1m",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
        )
    except Exception as exc:
        LOG.exception("Quote refresh failed")
        return f"Quote refresh failed; previous prices retained ({type(exc).__name__})."
    quotes = {}
    if data is not None and not data.empty:
        closes = data["Close"] if "Close" in data else pd.DataFrame()
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(tickers[0])
        for ticker in tickers:
            if ticker not in closes:
                continue
            series = closes[ticker].replace([np.inf, -np.inf], np.nan).dropna()
            series = series[series > 0]
            if not series.empty:
                stamp = pd.Timestamp(series.index[-1])
                stamp = (
                    stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                )
                quotes[ticker] = (float(series.iloc[-1]), stamp.isoformat())
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for ticker in tickers:
            conn.execute(
                "UPDATE portfolio SET quote_updated_at=CASE WHEN quote_checked_at IS NULL THEN NULL ELSE quote_updated_at END, quote_checked_at=? WHERE ticker=?",
                (now.isoformat(), ticker),
            )
        if quotes:
            for ticker, (price, stamp) in quotes.items():
                # Derive values from the current row: a concurrent trade cannot be overwritten.
                conn.execute(
                    "UPDATE portfolio SET current_price=?,market_value=?*shares,Total_Profit_Loss=(?-avg_price)*shares,quote_updated_at=? WHERE ticker=?",
                    (price, price, price, stamp, ticker),
                )
            record_valuation(conn)
    missing = sorted(set(tickers) - set(quotes))
    return f"Refreshed {len(quotes)} quotes." + (
        f" No quote returned for {', '.join(missing)}; previous values retained." if missing else ""
    )
