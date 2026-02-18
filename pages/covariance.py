import sqlite3

import dash
from dash import Input, Output, dcc, html, dash_table
import numpy as np
import pandas as pd
import plotly.express as px
import yfinance as yf


DB_PATH = "portfolio.db"
LOOKBACK_PERIOD = "1y"
LOOKBACK_INTERVAL = "1d"
TRADING_DAYS_PER_YEAR = 252


dash.register_page(__name__, path="/covariance", name="Covariance")


def _metric_card(title, value_id):
    return html.Div(
        [
            html.Div(title, style={"fontWeight": "bold", "marginBottom": "4px"}),
            html.Div("--", id=value_id, style={"fontSize": "18px"}),
        ],
        style={
            "flex": "1",
            "minWidth": "220px",
            "padding": "10px",
            "border": "1px solid #e5e5e5",
            "borderRadius": "8px",
            "backgroundColor": "#fafafa",
        },
    )


layout = html.Div(
    [
        html.H1(
            "Portfolio Covariance Matrix",
            style={"textAlign": "center", "marginBottom": "20px", "color": "#EA84FC"},
        ),
        html.Div(
            [
                _metric_card("Portfolio Annualized Volatility", "covariance-metric-portfolio-vol"),
                _metric_card("SPY Volatility Comparison", "covariance-metric-spy-vol"),
                _metric_card("Diversification Ratio", "covariance-metric-div-ratio"),
            ],
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"},
        ),
        html.Div(id="covariance-status", style={"marginBottom": "12px"}),
        dcc.Graph(id="covariance-heatmap"),
        dash_table.DataTable(
            id="covariance-table",
            data=[],
            columns=[],
            style_header={"backgroundColor": "#EA84FC", "fontWeight": "bold", "color": "black"},
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "center", "padding": "6px"},
        ),
        dcc.Interval(id="covariance-refresh", interval=60 * 1000, n_intervals=0),
    ]
)


def _empty_figure(message):
    fig = px.imshow([[0]], text_auto=False)
    fig.update_traces(showscale=False, hoverinfo="skip")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        title="Covariance Matrix",
        annotations=[
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 15},
            }
        ],
    )
    return fig


def _default_metrics():
    return "--", "--", "--"


def _load_holdings():
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql(
            "SELECT ticker, market_value, shares, current_price FROM portfolio",
            conn,
        )

    if df.empty:
        return df

    df["ticker"] = (
        df["ticker"]
        .astype(str)
        .str.strip()
        .str.upper()
    )
    df = df[df["ticker"] != ""]
    return df


def _extract_prices(data, symbols):
    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        level0 = set(data.columns.get_level_values(0))
        if "Adj Close" in level0:
            prices = data["Adj Close"]
        elif "Close" in level0:
            prices = data["Close"]
        else:
            return pd.DataFrame()

        if isinstance(prices, pd.Series):
            prices = prices.to_frame()

        prices.columns = [str(col).upper().strip() for col in prices.columns]
        return prices

    if "Adj Close" in data.columns:
        series = data["Adj Close"]
    elif "Close" in data.columns:
        series = data["Close"]
    else:
        return pd.DataFrame()

    column_name = symbols[0].upper().strip() if symbols else "PRICE"
    return series.to_frame(name=column_name)


def _format_metric_texts(portfolio_vol_ann, spy_vol_ann, diversification_ratio):
    portfolio_text = "--" if portfolio_vol_ann is None else f"{portfolio_vol_ann * 100:.2f}%"

    if spy_vol_ann is None:
        spy_text = "SPY: N/A"
    else:
        if portfolio_vol_ann is None:
            spread_text = "Spread N/A"
        else:
            spread_pp = (portfolio_vol_ann - spy_vol_ann) * 100
            spread_text = f"Spread {spread_pp:+.2f} pp"
        spy_text = f"SPY {spy_vol_ann * 100:.2f}% | {spread_text}"

    diversification_text = "--" if diversification_ratio is None else f"{diversification_ratio:.3f}"
    return portfolio_text, spy_text, diversification_text


def _build_weight_series(holdings, valid_tickers):
    if not valid_tickers:
        return pd.Series(dtype=float)

    market_value = pd.to_numeric(holdings["market_value"], errors="coerce")
    shares = pd.to_numeric(holdings["shares"], errors="coerce")
    current_price = pd.to_numeric(holdings["current_price"], errors="coerce")

    fallback_value = shares * current_price
    position_value = market_value.where(market_value > 0, fallback_value)
    position_value = position_value.where(position_value > 0, 0.0).fillna(0.0)

    by_ticker = pd.Series(position_value.values, index=holdings["ticker"]).groupby(level=0).sum()
    selected = by_ticker.reindex(valid_tickers).fillna(0.0)

    total_value = float(selected.sum())
    if total_value > 0:
        return selected / total_value

    equal_weight = 1.0 / len(valid_tickers)
    return pd.Series(np.full(len(valid_tickers), equal_weight), index=valid_tickers)


def _build_covariance_outputs(holdings):
    default_portfolio, default_spy, default_div = _default_metrics()

    if holdings.empty:
        return (
            html.Div("No holdings found."),
            _empty_figure("No holdings found."),
            [],
            [],
            default_portfolio,
            default_spy,
            default_div,
        )

    tickers = sorted(holdings["ticker"].dropna().unique().tolist())
    symbols = sorted(set(tickers + ["SPY"]))

    try:
        history = yf.download(
            tickers=symbols,
            period=LOOKBACK_PERIOD,
            interval=LOOKBACK_INTERVAL,
            progress=False,
            auto_adjust=False,
            group_by="column",
            threads=False,
        )
    except Exception as exc:
        return (
            html.Div(f"Unable to fetch market data: {exc}"),
            _empty_figure("Market data request failed."),
            [],
            [],
            default_portfolio,
            default_spy,
            default_div,
        )

    prices_all = _extract_prices(history, symbols)
    if prices_all.empty:
        return (
            html.Div("Insufficient price history to compute covariance."),
            _empty_figure("No usable price history."),
            [],
            [],
            default_portfolio,
            default_spy,
            default_div,
        )

    spy_vol_ann = None
    if "SPY" in prices_all.columns:
        spy_returns = prices_all["SPY"].ffill().dropna().pct_change().dropna()
        if spy_returns.shape[0] >= 2:
            spy_vol_ann = float(spy_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))

    requested = set(tickers)
    portfolio_prices = prices_all[[col for col in prices_all.columns if col in requested]]
    portfolio_prices = portfolio_prices.dropna(axis=1, how="all")
    portfolio_prices = portfolio_prices.ffill().dropna(how="all")

    returns = portfolio_prices.pct_change().dropna(how="all")
    returns = returns.dropna(axis=1, how="all")

    portfolio_vol_ann = None
    diversification_ratio = None
    valid_tickers = returns.columns.tolist()

    if returns.shape[0] >= 2 and returns.shape[1] >= 1:
        cov_for_metrics = returns.cov().reindex(index=valid_tickers, columns=valid_tickers).fillna(0.0)
        weights = _build_weight_series(holdings, valid_tickers)

        weight_vec = weights.to_numpy(dtype=float)
        cov_values = cov_for_metrics.to_numpy(dtype=float)

        variance_daily = float(weight_vec.T @ cov_values @ weight_vec)
        variance_daily = max(variance_daily, 0.0)
        sigma_portfolio_daily = float(np.sqrt(variance_daily))

        portfolio_vol_ann = sigma_portfolio_daily * np.sqrt(TRADING_DAYS_PER_YEAR)

        if len(valid_tickers) == 1:
            diversification_ratio = 1.0
        elif sigma_portfolio_daily > 0:
            asset_vols = np.sqrt(np.clip(np.diag(cov_values), 0.0, None))
            diversification_ratio = float(np.dot(weight_vec, asset_vols) / sigma_portfolio_daily)

    portfolio_metric, spy_metric, div_metric = _format_metric_texts(
        portfolio_vol_ann,
        spy_vol_ann,
        diversification_ratio,
    )

    used_count = len(valid_tickers)
    observations = returns.shape[0]
    dropped = sorted(requested - set(valid_tickers))

    status_parts = [
        "Window: 1 year (daily).",
        f"Tickers used: {used_count} / {len(tickers)}.",
        f"Observations: {observations}.",
    ]
    if dropped:
        status_parts.append(f"Filtered due to missing data: {', '.join(dropped)}.")

    if returns.shape[0] < 2 or returns.shape[1] < 2:
        status_parts.append("Need at least 2 tickers with usable return history for covariance.")
        return (
            html.Div(" ".join(status_parts)),
            _empty_figure("Insufficient return history for covariance."),
            [],
            [],
            portfolio_metric,
            spy_metric,
            div_metric,
        )

    cov = returns.cov().sort_index().sort_index(axis=1)
    if cov.empty or cov.shape[0] < 2:
        status_parts.append("Covariance matrix unavailable after filtering.")
        return (
            html.Div(" ".join(status_parts)),
            _empty_figure("Covariance matrix unavailable."),
            [],
            [],
            portfolio_metric,
            spy_metric,
            div_metric,
        )

    zmax = float(cov.abs().to_numpy().max())
    if zmax == 0:
        zmax = 1e-12

    fig = px.imshow(
        cov.values,
        x=cov.columns,
        y=cov.index,
        aspect="auto",
        color_continuous_scale="RdBu",
        zmin=-zmax,
        zmax=zmax,
        labels={"x": "Ticker", "y": "Ticker", "color": "Covariance"},
    )
    fig.update_traces(
        hovertemplate="X: %{x}<br>Y: %{y}<br>Covariance: %{z:.6f}<extra></extra>"
    )
    fig.update_layout(title="Covariance Matrix (Daily Returns, 1Y)")

    display_df = cov.copy()
    display_df.insert(0, "ticker", display_df.index)
    for col in cov.columns:
        display_df[col] = display_df[col].map(lambda value: f"{value:.6f}")

    columns = [{"name": "Ticker", "id": "ticker"}] + [
        {"name": col, "id": col} for col in cov.columns
    ]

    return (
        html.Div(" ".join(status_parts)),
        fig,
        display_df.to_dict("records"),
        columns,
        portfolio_metric,
        spy_metric,
        div_metric,
    )


@dash.callback(
    Output("covariance-status", "children"),
    Output("covariance-heatmap", "figure"),
    Output("covariance-table", "data"),
    Output("covariance-table", "columns"),
    Output("covariance-metric-portfolio-vol", "children"),
    Output("covariance-metric-spy-vol", "children"),
    Output("covariance-metric-div-ratio", "children"),
    Input("covariance-refresh", "n_intervals"),
)
def refresh_covariance(_):
    holdings = _load_holdings()
    return _build_covariance_outputs(holdings)
