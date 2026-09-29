import dash
import numpy as np
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html

from Services.components import metric_card as _metric_card
from Services.helper import load_data
from Services.ledger import account_performance
from Services.market import clean_returns, coverage_text, get_historical_prices
from Services.performance import (
    compute_performance_metrics,
    compute_portfolio_returns,
    compute_returns,
    compute_ttwr,
    drawdowns,
)
from Services.settings import get_settings

dash.register_page(__name__, path="/analytics", name="Analytics", title="Analytics", order=2)
layout = html.Div(
    [
        dcc.Location(id="analytics_location"),
        html.H2("Analytics", className="page-title"),
        html.Div(
            [
                _metric_card(label, key)
                for label, key in [
                    ("Sharpe Ratio", "sharpe"),
                    ("Sortino Ratio", "sortino"),
                    ("Beta", "beta"),
                    ("Alpha (annualized)", "alpha"),
                    ("Current allocation return", "ttwr"),
                    ("Max Drawdown", "max_drawdown"),
                ]
            ],
            className="summary-grid",
        ),
        html.P(
            "Historical model of today's invested holdings, rebalanced daily; cash is excluded. "
            "It is separate from recorded account performance below. Returns use adjusted prices and matching dates."
        ),
        html.Div(id="analytics-status", className="data-status"),
        dcc.Graph(id="performance_chart"),
        dcc.Graph(id="drawdown_chart"),
        html.H3("Recorded account performance"),
        html.Div(id="account-performance-status"),
        dcc.Graph(id="account-performance-chart"),
    ]
)


@dash.callback(
    Output("performance_chart", "figure"),
    Output("drawdown_chart", "figure"),
    Output("sharpe", "children"),
    Output("sortino", "children"),
    Output("beta", "children"),
    Output("alpha", "children"),
    Output("ttwr", "children"),
    Output("max_drawdown", "children"),
    Output("analytics-status", "children"),
    Input("analytics_location", "pathname"),
    Input("analysis-period", "value"),
    Input("analysis-benchmark", "value"),
    Input("settings-version", "data"),
)
def update_analytics(pathname, period="1y", benchmark="SPY", _version=None):
    empty = px.line()

    def unavailable(message):
        return empty, empty, *("N/A",) * 6, message

    holdings = load_data()
    if holdings.empty or holdings.market_value.sum() <= 0:
        return unavailable("No invested holdings.")
    tickers = holdings.ticker.tolist()
    prices = get_historical_prices(tickers + [benchmark], period=period)
    if prices.empty or benchmark not in prices:
        return unavailable("Price history or the selected benchmark is unavailable.")
    # Keep low-sample data out of displayed estimates in normal operation.
    returns = clean_returns(prices.reindex(columns=tickers), min_observations=30)
    bench = compute_returns(prices[benchmark])
    common = returns.index.intersection(bench.index)
    returns, bench = returns.loc[common], bench.loc[common]
    status = coverage_text(holdings, returns, period, benchmark)
    if returns.empty or returns.shape[1] == 0 or len(returns) < 30:
        return unavailable(status + " At least 30 complete common observations are required.")
    weights = holdings.set_index("ticker").market_value.reindex(returns.columns).fillna(0)
    weights /= weights.sum()
    portfolio = compute_portfolio_returns(returns, weights)
    rf = get_settings()["risk_free"]
    metrics = compute_performance_metrics(portfolio, bench, rf)
    cumulative = pd.DataFrame(
        {"Current allocation": (1 + portfolio).cumprod() - 1, benchmark: (1 + bench).cumprod() - 1}
    )
    baseline = pd.DataFrame(
        0.0,
        index=[prices.index[prices.index < common[0]][-1]]
        if any(prices.index < common[0])
        else [common[0] - pd.Timedelta(days=1)],
        columns=cumulative.columns,
    )
    perf = px.line(
        pd.concat([baseline, cumulative]),
        title="Historical return of current allocation",
        labels={"value": "Return", "index": "Date"},
    )
    perf.update_yaxes(tickformat=".1%")
    dd = px.area(drawdowns(portfolio), title="Drawdown from starting value or later peak")
    dd.update_yaxes(tickformat=".1%")

    def fmt(value, percent=False):
        return (
            "N/A"
            if value is None or not np.isfinite(value)
            else (f"{value:.2%}" if percent else f"{value:.2f}")
        )

    status += f" Annual risk-free assumption: {rf:.2%}."
    return (
        perf,
        dd,
        fmt(metrics["sharpe"]),
        fmt(metrics["sortino"]),
        fmt(metrics["beta"]),
        fmt(metrics["alpha"], True),
        fmt(compute_ttwr(portfolio), True),
        fmt(metrics["max_drawdown"], True),
        status,
    )


@dash.callback(
    Output("account-performance-status", "children"),
    Output("account-performance-chart", "figure"),
    Input("analytics_location", "pathname"),
)
def recorded_performance(_pathname):
    values = account_performance()
    if len(values) < 2:
        return (
            "Account history starts with the opening balance. More recorded valuations are needed.",
            px.line(),
        )
    values["timestamp"] = pd.to_datetime(values.timestamp, utc=True)
    values["Time-weighted return"] = values.growth - 1
    fig = px.line(
        values,
        x="timestamp",
        y="Time-weighted return",
        title="Recorded account return (cash flows excluded)",
    )
    fig.update_yaxes(tickformat=".1%")
    return (
        f"Since {values.timestamp.iloc[0]:%Y-%m-%d}: {values.growth.iloc[-1] - 1:.2%}. "
        "Uses recorded quote and transaction valuations, including cash, dividends and fees. "
        "No performance is reconstructed before the opening balance; stale quotes can affect valuations."
    ), fig
