
import dash
from dash import Input, Output, html
from dash import dcc
import numpy as np
import pandas as pd
import yfinance as yf
import plotly.express as px

from pages.covariance import _metric_card
from Services.helper import load_data

print("analytics module loaded")





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

def compute_portfolio_returns(returns,weights):
    return (returns*weights).sum(axis=1)

#calculate main metrics
def compute_performance_metrics(portfolio_returns , benchmark_returns):

    rf = 0.04
    rf_daily = rf / TRADING_DAYS
    excess_p = portfolio_returns - rf_daily
    excess_m = benchmark_returns - rf_daily
    
    # Regression for beta and alpha
    slope, intercept = np.polyfit(excess_m, excess_p, 1)
    beta = slope
    alpha_daily = intercept
    alpha = alpha_daily * TRADING_DAYS

    mean_return = portfolio_returns.mean() * TRADING_DAYS
    volatility = portfolio_returns.std() * np.sqrt(TRADING_DAYS)
    sharpe_ratio = (mean_return - rf) / volatility if volatility != 0 else None

    downside = portfolio_returns[portfolio_returns < 0]
    downside_std = downside.std() * np.sqrt(TRADING_DAYS)
    
    sortino = (mean_return - rf) / downside_std if downside_std != 0 else None

    cumulative = (1 + portfolio_returns).cumprod()
    cummax = cumulative.cummax()
    drawdown = (cumulative / cummax) - 1
    max_drawdown = drawdown.min()

    return {"sharpe": sharpe_ratio, "sortino": sortino, "beta": beta, "alpha": alpha, "max_drawdown": max_drawdown}


#Portfolio vs SPY

def _extract_adj_close(data, tickers):
    if data is None or data.empty:
        return pd.DataFrame()

    # yfinance can return MultiIndex columns (e.g., ('Adj Close', 'AAPL')) or single-level.
    if isinstance(data.columns, pd.MultiIndex):
        if "Adj Close" in data.columns.get_level_values(0):
            data = data["Adj Close"]
        elif "Close" in data.columns.get_level_values(0):
            data = data["Close"]
        else:
            return pd.DataFrame()

    # If the DataFrame still contains an 'Adj Close' column, use it.
    if "Adj Close" in data.columns:
        data = data["Adj Close"]
    elif "Close" in data.columns:
        data = data["Close"]

    # Ensure output is a DataFrame with tickers as columns.
    if isinstance(data, pd.Series):
        data = data.to_frame(name=tickers[0] if tickers else "price")

    return data


def get_historical_prices(tickers, period="6mo", interval="1d"):
    all_prices = {}
    for ticker in tickers:
        try:
            data = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                threads=False,
                auto_adjust=True,
            )
            if not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    if "Close" in data.columns.get_level_values(0):
                        adj_close = data["Close"].iloc[:, 0]
                    else:
                        continue
                else:
                    if "Adj Close" in data.columns:
                        adj_close = data["Adj Close"]
                    elif "Close" in data.columns:
                        adj_close = data["Close"]
                    else:
                        continue
                if not adj_close.empty:
                    all_prices[ticker] = adj_close
        except Exception as e:
            print(f"[analytics] Failed to download {ticker}: {e}")
            continue
    if not all_prices:
        return pd.DataFrame()
    df = pd.DataFrame(all_prices)
    return df

#Layout

layout = html.Div([

    dcc.Location(id='analytics_location'),

    html.H2("Portfolio Performance Analytics"),

    html.Div([
        _metric_card("Sharpe Ratio", "sharpe"),
        _metric_card("Sortino Ratio", "sortino"),
        _metric_card("Beta", "beta"),
        _metric_card("Alpha", "alpha"),
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
        Output("max_drawdown","children"),
        Input('analytics_location', 'pathname')
    )
    def update_analytics(pathname):
        print("[analytics] callback triggered")
        # Get portfolio data
        df = load_data()
        print(f"[analytics] portfolio df shape: {df.shape}")
        if not df.empty:
            print(f"[analytics] portfolio df head: {df.head()}")
        if df.empty:
            # Return empty figures and N/A
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"
        
        # Limit to top 5 tickers by market value to keep data fetch fast
        df_sorted = df.sort_values(by="market_value", ascending=False).head(5)
        tickers = df_sorted["ticker"].tolist()

        market_values = pd.to_numeric(df_sorted["market_value"], errors="coerce").fillna(0)
        if market_values.sum() <= 0:
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        weights = market_values / market_values.sum()

        # Get historical prices
        try:
            prices = get_historical_prices(tickers, period="1y", interval="1d")
        except Exception as e:
            print(f"[analytics] price download error: {e}")
            prices = pd.DataFrame()

        print(f"[analytics] tickers: {tickers}")
        print(f"[analytics] weights: {weights.values}")
        print(f"[analytics] prices shape: {prices.shape}, columns: {prices.columns.tolist() if not prices.empty else 'empty'}")

        if prices.empty:
            print("[analytics] prices empty after download")
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        # Remove tickers without data
        prices = prices.dropna(axis=1, how="all")
        if prices.empty:
            print("[analytics] all tickers dropped; no price columns")
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        # Drop tickers with any missing data to avoid NaN in returns
        prices = prices.dropna(axis=1)
        print(f"[analytics] after dropna any: prices shape: {prices.shape}, columns: {prices.columns.tolist() if not prices.empty else 'empty'}")
        if prices.empty:
            print("[analytics] all tickers have missing data; no complete price columns")
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        # Update tickers and weights to only include those with complete data
        available_tickers = prices.columns.tolist()
        df_sorted = df_sorted[df_sorted['ticker'].isin(available_tickers)]
        market_values = pd.to_numeric(df_sorted["market_value"], errors="coerce").fillna(0)
        if market_values.sum() <= 0:
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"
        weights = pd.Series(market_values.values / market_values.sum(), index=df_sorted['ticker'])

        returns = compute_returns(prices)
        print(f"[analytics] returns shape: {returns.shape}, columns: {returns.columns.tolist() if not returns.empty else 'empty'}")
        if returns.empty:
            print("[analytics] returns empty after pct_change")
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        if prices.empty:
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        returns = compute_returns(prices)

        # Benchmark SPY
        try:
            spy_raw = yf.download(
                "SPY",
                period="1y",
                interval="1d",
                progress=False,
                threads=False,
                auto_adjust=True,
            )
            if not spy_raw.empty:
                if isinstance(spy_raw.columns, pd.MultiIndex):
                    if "Close" in spy_raw.columns.get_level_values(0):
                        spy = spy_raw["Close"].iloc[:, 0]
                    else:
                        spy = pd.Series(dtype=float)
                else:
                    spy = spy_raw["Adj Close"] if "Adj Close" in spy_raw.columns else spy_raw["Close"] if "Close" in spy_raw.columns else pd.Series(dtype=float)
            else:
                spy = pd.Series(dtype=float)
        except Exception:
            spy = pd.Series(dtype=float)
        spy_returns = spy.pct_change().dropna()
        
        # Align dates
        common_index = returns.index.intersection(spy_returns.index)
        returns = returns.loc[common_index]
        spy_returns = spy_returns.loc[common_index]

        if len(common_index) < 2 or returns.empty or spy_returns.empty:
            print(f"[analytics] insufficient data after alignment: common_index={len(common_index)}, returns_cols={returns.shape}, spy={spy_returns.shape}")
            empty_fig = px.line()
            return empty_fig, empty_fig, "N/A", "N/A", "N/A", "N/A", "N/A"

        portfolio_returns = compute_portfolio_returns(returns, weights)
        print(f"[analytics] portfolio_returns sample: {portfolio_returns.head()}")
        
        metrics = compute_performance_metrics(portfolio_returns, spy_returns)
        print(f"[analytics] metrics: {metrics}")
        
        # Cumulative Performance
        portfolio_cum = (1 + portfolio_returns).cumprod()
        spy_cum = (1 + spy_returns).cumprod()
        print(f"[analytics] final portfolio cum: {portfolio_cum.iloc[-1]:.4f}, spy cum: {spy_cum.iloc[-1]:.4f}")
        
        df_perf = pd.DataFrame({
            "Portfolio": portfolio_cum,
            "SPY": spy_cum
        })
        fig_perf = px.line(df_perf, title="Cumulative Performance", labels={"value": "Cumulative Return", "index": "Date"})
        
        # Drawdown
        drawdown = portfolio_cum / portfolio_cum.cummax() - 1
        fig_drawdown = px.area(drawdown, title="Drawdown", labels={"value": "Drawdown", "index": "Date"})
        fig_drawdown.update_yaxes(tickformat=".1%")
        
        # Format metrics
        def format_metric(val, percent=False):
            if val is None:
                return "N/A"
            elif isinstance(val, float):
                if percent:
                    return f"{val:.2%}"
                else:
                    return f"{val:.2f}"
            else:
                return str(val)
        
        return (
            fig_perf,
            fig_drawdown,
            format_metric(metrics['sharpe']),
            format_metric(metrics['sortino']),
            format_metric(metrics['beta']),
            format_metric(metrics['alpha'], percent=True),
            format_metric(metrics['max_drawdown'], percent=True),
        )