"""Shared adjusted history, bounded caching and complete-date risk samples."""

import logging
import threading
import time

import numpy as np
import pandas as pd
import yfinance as yf

PERIODS = ("6mo", "1y", "3y", "5y")
BENCHMARKS = ("SPY", "QQQ", "VT", "AGG")
_cache = {}
_lock = threading.Lock()
LOG = logging.getLogger(__name__)


def extract_prices(data, tickers):
    if data is None or data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        field = "Adj Close" if "Adj Close" in data.columns.get_level_values(0) else "Close"
        if field not in data.columns.get_level_values(0):
            return pd.DataFrame()
        result = data[field].copy()
        if isinstance(result, pd.Series):
            result = result.to_frame()
        result.columns = [str(c).upper() for c in result.columns]
    else:
        field = "Adj Close" if "Adj Close" in data else "Close"
        if field not in data:
            return pd.DataFrame()
        result = data[[field]].rename(columns={field: tickers[0]})
    result.index = pd.to_datetime(result.index, utc=True).tz_convert(None)
    return (
        result.sort_index()
        .loc[lambda x: ~x.index.duplicated(keep="last")]
        .replace([np.inf, -np.inf], np.nan)
        .where(lambda x: x > 0)
        .dropna(axis=1, how="all")
    )


def get_historical_prices(tickers, period="1y", interval="1d"):
    tickers = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not tickers:
        return pd.DataFrame()
    if period not in PERIODS or interval != "1d":
        raise ValueError("Unsupported history window or interval.")
    key = (tuple(tickers), period, interval)
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1].copy()
    try:
        data = yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
            group_by="column",
            threads=False,
        )
        prices = extract_prices(data, tickers)
    except Exception:
        LOG.exception("Historical price download failed")
        return pd.DataFrame()
    if not prices.empty:
        with _lock:
            if len(_cache) >= 32:
                _cache.pop(next(iter(_cache)))
            _cache[key] = (time.monotonic(), prices.copy())
    return prices


def clean_returns(prices, min_observations=30, log=False):
    values = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    values = values.dropna(axis=1, thresh=min_observations).dropna()
    if log:
        values = np.log1p(values)
    return values


def coverage_text(holdings, returns, period, benchmark=None):
    included = list(returns.columns)
    values = holdings.groupby("ticker")["market_value"].sum()
    total = float(values.sum())
    covered = float(values.reindex(included).fillna(0).sum())
    missing = sorted(set(values.index) - set(included))
    dates = (
        f"{returns.index.min():%Y-%m-%d} to {returns.index.max():%Y-%m-%d}"
        if not returns.empty
        else "no complete common dates"
    )
    return (
        (
            f"Requested window: {period}. Actual sample: {dates}; {len(returns)} daily observations. "
            f"Holdings: {len(included)}/{len(values)}; value coverage: {covered / total:.1%}. "
            if total > 0
            else "No invested holdings. "
        )
        + (f"Excluded: {', '.join(missing)}. " if missing else "")
        + (f"Benchmark: {benchmark}." if benchmark else "")
    )
