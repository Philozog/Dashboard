
import dash
from dash import Input, Output, html
from dash import dcc
import numpy as np
import pandas as pd
import yfinance as yf
import plotly.express as px

from pages.covariance import _metric_card
from Services.helper import load_data






dash.register_page(
    __name__,
    path="/analytics",
    name="Analytics",
    title="Analytics",
)

TRADING_DAYS=252

#calculate returns
def compute_returns(prices):
    return prices.pct_change().dropna()

def compute_portfolio_returns(returns, weights):
    weights_aligned = weights.reindex(returns.columns, fill_value=0)
    return (returns * weights_aligned).sum(axis=1)

def compute_ttwr(portfolio_returns):
    if portfolio_returns is None or portfolio_returns.empty:
        return None
    return (1 + portfolio_returns).prod() - 1

#calculate main metrics
def compute_performance_metrics(portfolio_returns , benchmark_returns):

   #Treasuries approximate risk-free rate, using 10-year yield as a proxy
    rf = 0.04
    
    mean_return = portfolio_returns.mean() * TRADING_DAYS
    mean_benchmark = benchmark_returns.mean() * TRADING_DAYS
    volatility = portfolio_returns.std() * np.sqrt(TRADING_DAYS)
    sharpe_ratio = (mean_return - rf) / volatility if volatility != 0 else None

    # Calculate beta using covariance
    cov_matrix = np.cov(portfolio_returns, benchmark_returns)
    beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] != 0 else None
    
    # Calculate alpha: alpha = R_p - [R_f + beta * (R_m - R_f)]
    alpha = mean_return - (rf + beta * (mean_benchmark - rf)) if beta is not None else None
    
    downside = portfolio_returns[portfolio_returns < 0]
    downside_std = downside.std() * np.sqrt(TRADING_DAYS)
    
    sortino = (mean_return - rf) / downside_std if downside_std != 0 else None

    cumulative = (1 + portfolio_returns).cumprod()
    cummax = cumulative.cummax()
    drawdown = (cumulative / cummax) - 1
    max_drawdown = drawdown.min()

    return {"sharpe": sharpe_ratio, "sortino": sortino, "beta": beta, "alpha": alpha, "max_drawdown": max_drawdown}


def get_historical_prices(tickers, period="1y", interval="1d"):
    if not tickers:
        return pd.DataFrame()
    try:
        data = yf.download(
            tickers=sorted(set(t.upper() for t in tickers)),
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
            group_by="column",
            threads=False,
        )
    except Exception:
        return pd.DataFrame()

    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        level0 = set(data.columns.get_level_values(0))
        price_col = "Close" if "Close" in level0 else ("Adj Close" if "Adj Close" in level0 else None)
        if price_col is None:
            return pd.DataFrame()
        df = data[price_col].copy()
        df.columns = [str(c).upper() for c in df.columns]
    else:
        price_col = "Close" if "Close" in data.columns else ("Adj Close" if "Adj Close" in data.columns else None)
        if price_col is None:
            return pd.DataFrame()
        df = data[[price_col]].copy()
        df.columns = [tickers[0].upper()]

    return df.dropna(axis=1, how="all")

#Layout

layout = html.Div([

    dcc.Location(id='analytics_location'),

    html.H2("Portfolio Performance Analytics"),

    html.Div([
        _metric_card("Sharpe Ratio", "sharpe"),
        _metric_card("Sortino Ratio", "sortino"),
        _metric_card("Beta", "beta"),
        _metric_card("Alpha", "alpha"),
        _metric_card("TTWR", "ttwr"),
        _metric_card("Max Drawdown", "max_drawdown"),
    ], style={"display": "flex", "gap": "10px"}),

    dcc.Graph(id="performance_chart"),
    dcc.Graph(id="drawdown_chart")

])


#Callbacks

if not hasattr(dash, '_analytics_callback_registered'):
    dash._analytics_callback_registered = True

    @dash.callback( 
        Output("performance_chart","figure"), 
        Output("drawdown_chart","figure"), 
        Output("sharpe","children"), 
        Output("sortino","children"), 
        Output("beta","children"), 
        Output("alpha","children"), 
        Output("ttwr","children"),
        Output("max_drawdown","children"),
        Input('analytics_location', 'pathname')
    )
    def update_analytics(pathname):
        empty_fig = px.line()
        na = ("N/A",) * 6

        df = load_data()
        if df.empty:
            return empty_fig, empty_fig, *na

        df = df.copy()
        df["ticker"] = df["ticker"].fillna("").astype(str).str.strip().str.upper()
        df = df[df["ticker"] != ""]
        df["market_value"] = pd.to_numeric(df["market_value"], errors="coerce").fillna(0)
        df = df.groupby("ticker", as_index=False)["market_value"].sum()
        df_sorted = df.sort_values("market_value", ascending=False)
        tickers = df_sorted["ticker"].tolist()

        market_values = pd.to_numeric(df_sorted["market_value"], errors="coerce").fillna(0)
        if market_values.sum() <= 0:
            return empty_fig, empty_fig, *na

        # Single batch download — portfolio tickers + SPY together
        all_prices = get_historical_prices(tickers + ["SPY"], period="1y")
        if all_prices.empty:
            return empty_fig, empty_fig, *na

        spy_series = all_prices["SPY"] if "SPY" in all_prices.columns else pd.Series(dtype=float)
        prices = all_prices.drop(columns=["SPY"], errors="ignore")
        prices = prices.dropna(axis=1, how="all")
        if prices.empty:
            return empty_fig, empty_fig, *na

        available_tickers = prices.columns.tolist()
        df_sorted = df_sorted[df_sorted["ticker"].isin(available_tickers)]
        market_values = pd.to_numeric(df_sorted["market_value"], errors="coerce").fillna(0)
        if market_values.sum() <= 0:
            return empty_fig, empty_fig, *na
        weights = pd.Series(market_values.values / market_values.sum(), index=df_sorted["ticker"])

        returns = compute_returns(prices)
        if returns.empty:
            return empty_fig, empty_fig, *na

        spy_returns = spy_series.pct_change().dropna()
        common_index = returns.index.intersection(spy_returns.index)
        returns = returns.loc[common_index]
        spy_returns = spy_returns.loc[common_index]

        if len(common_index) < 2:
            return empty_fig, empty_fig, *na

        portfolio_returns = compute_portfolio_returns(returns, weights)
        metrics = compute_performance_metrics(portfolio_returns, spy_returns)
        ttwr = compute_ttwr(portfolio_returns)

        portfolio_cum = (1 + portfolio_returns).cumprod()
        spy_cum = (1 + spy_returns).cumprod()

        fig_perf = px.line(
            pd.DataFrame({"Portfolio": portfolio_cum, "SPY": spy_cum}),
            title="Cumulative Performance",
            labels={"value": "Cumulative Return", "index": "Date"},
        )
        drawdown = portfolio_cum / portfolio_cum.cummax() - 1
        fig_drawdown = px.area(drawdown, title="Drawdown", labels={"value": "Drawdown", "index": "Date"})
        fig_drawdown.update_yaxes(tickformat=".1%")

        def fmt(val, percent=False):
            if val is None:
                return "N/A"
            return f"{val:.2%}" if percent else f"{val:.2f}"

        return (
            fig_perf,
            fig_drawdown,
            fmt(metrics["sharpe"]),
            fmt(metrics["sortino"]),
            fmt(metrics["beta"]),
            html.S(fmt(metrics["alpha"], percent=True)),
            fmt(ttwr, percent=True),
            fmt(metrics["max_drawdown"], percent=True),
        )
