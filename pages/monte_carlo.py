import dash
from dash import Input, Output, dcc, html
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

from pages.covariance import _metric_card
from Services.helper import load_data


TRADING_DAYS_PER_YEAR = 252
LOOKBACK_PERIOD = "5y"
LOOKBACK_INTERVAL = "1d"
DEFAULT_SIMULATIONS = 10000
DEFAULT_YEARS = 1


dash.register_page(
    __name__,
    path="/monte-carlo",
    name="Monte Carlo",
    title="Monte Carlo",
)


def _empty_figure(title, message):
    fig = go.Figure()
    fig.update_layout(
        title=title,
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
        xaxis={"visible": False},
        yaxis={"visible": False},
        template="plotly_white",
    )
    return fig


def _load_holdings():
    df = load_data().copy()
    if df.empty:
        return df

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["ticker"] != ""]

    df["market_value_num"] = pd.to_numeric(df["market_value"], errors="coerce")
    df["shares_num"] = pd.to_numeric(df["shares"], errors="coerce")
    df["current_price_num"] = pd.to_numeric(df["current_price"], errors="coerce")

    fallback_value = df["shares_num"].fillna(0) * df["current_price_num"].fillna(0)
    df["position_value"] = df["market_value_num"].where(df["market_value_num"] > 0, fallback_value)
    df["position_value"] = df["position_value"].where(df["position_value"] > 0, 0.0).fillna(0.0)
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

        prices.columns = [str(column).upper().strip() for column in prices.columns]
        return prices

    if "Adj Close" in data.columns:
        series = data["Adj Close"]
    elif "Close" in data.columns:
        series = data["Close"]
    else:
        return pd.DataFrame()

    symbol = symbols[0].upper().strip() if symbols else "PRICE"
    return series.to_frame(name=symbol)


def _download_prices(tickers):
    if not tickers:
        return pd.DataFrame()

    try:
        history = yf.download(
            tickers=sorted(set(tickers)),
            period=LOOKBACK_PERIOD,
            interval=LOOKBACK_INTERVAL,
            progress=False,
            auto_adjust=True,
            group_by="column",
            threads=False,
        )
    except Exception:
        return pd.DataFrame()

    prices = _extract_prices(history, tickers)
    if prices.empty:
        return prices

    prices = prices.ffill().dropna(axis=1, how="all")
    return prices


def _build_weights(holdings, valid_tickers):
    position_values = (
        holdings.groupby("ticker", as_index=True)["position_value"]
        .sum()
        .reindex(valid_tickers)
        .fillna(0.0)
    )

    total_value = float(position_values.sum())
    if total_value <= 0:
        return pd.Series(dtype=float), 0.0

    return position_values / total_value, total_value


def _simulate_portfolio_paths(returns, weights, initial_value, years, simulations):
    steps = max(int(years * TRADING_DAYS_PER_YEAR), 1)
    daily_mean = returns.mean().to_numpy(dtype=float)
    daily_cov = returns.cov().to_numpy(dtype=float)
    weight_vector = weights.reindex(returns.columns).fillna(0.0).to_numpy(dtype=float)

    # Small diagonal jitter improves stability when the covariance matrix is nearly singular.
    daily_cov = daily_cov + np.eye(daily_cov.shape[0]) * 1e-10

    rng = np.random.default_rng(42)
    simulated_asset_returns = rng.multivariate_normal(
        mean=daily_mean,
        cov=daily_cov,
        size=(steps, simulations),
        check_valid="ignore",
    )
    simulated_portfolio_returns = simulated_asset_returns @ weight_vector
    growth = np.cumprod(np.exp(simulated_portfolio_returns), axis=0)

    starting_row = np.full((1, simulations), float(initial_value))
    path_values = np.vstack([starting_row, initial_value * growth])
    time_axis = np.arange(path_values.shape[0]) / TRADING_DAYS_PER_YEAR
    return time_axis, path_values


def _format_currency(value):
    return f"${value:,.0f}"


def _format_percent(value):
    return f"{value:.1%}"


def _build_projection_chart(years_axis, path_values):
    percentile_5 = np.percentile(path_values, 5, axis=1)
    percentile_25 = np.percentile(path_values, 25, axis=1)
    percentile_50 = np.percentile(path_values, 50, axis=1)
    percentile_75 = np.percentile(path_values, 75, axis=1)
    percentile_95 = np.percentile(path_values, 95, axis=1)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years_axis,
            y=percentile_95,
            mode="lines",
            line={"width": 0},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years_axis,
            y=percentile_5,
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(37, 99, 235, 0.15)",
            line={"width": 0},
            name="5th-95th percentile",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years_axis,
            y=percentile_75,
            mode="lines",
            line={"width": 0},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years_axis,
            y=percentile_25,
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(29, 78, 216, 0.25)",
            line={"width": 0},
            name="25th-75th percentile",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years_axis,
            y=percentile_50,
            mode="lines",
            line={"color": "#1d4ed8", "width": 3},
            name="Median path",
        )
    )
    fig.update_layout(
        title="Projected Portfolio Value Paths",
        xaxis_title="Years",
        yaxis_title="Portfolio Value",
        template="plotly_white",
        legend={"orientation": "h", "y": 1.1},
    )
    fig.update_yaxes(tickprefix="$", separatethousands=True)
    return fig


def _build_distribution_chart(final_values, initial_value):
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=final_values,
            nbinsx=40,
            marker={"color": "#60a5fa"},
            name="Ending values",
        )
    )
    for percentile, color in ((5, "#dc2626"), (50, "#1d4ed8"), (95, "#16a34a")):
        value = float(np.percentile(final_values, percentile))
        fig.add_vline(
            x=value,
            line_width=2,
            line_dash="dash",
            line_color=color,
            annotation_text=f"P{percentile}: {_format_currency(value)}",
            annotation_position="top",
        )

    fig.add_vline(
        x=float(initial_value),
        line_width=2,
        line_color="#475569",
        annotation_text=f"Today: {_format_currency(initial_value)}",
        annotation_position="bottom right",
    )
    fig.update_layout(
        title="Distribution of Ending Portfolio Values",
        xaxis_title="Ending Value",
        yaxis_title="Simulation Count",
        template="plotly_white",
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    return fig


def _build_explanation(current_value, median_value, downside_value, upside_value, loss_probability, years, simulations):
    return html.Div(
        [
            html.H4("How to read this", style={"marginTop": "0"}),
            html.P(
                f"This page takes your current holdings, converts them into portfolio weights, "
                f"uses about {LOOKBACK_PERIOD} of daily market history, and runs {simulations:,} random future paths "
                f"over {years} year{'s' if years != 1 else ''}."
            ),
            html.P(
                f"The median path ends near {_format_currency(median_value)}. "
                f"The 5th percentile ends near {_format_currency(downside_value)}, which is a rough stress case, "
                f"and the 95th percentile ends near {_format_currency(upside_value)}, which is a strong upside case."
            ),
            html.P(
                f"Starting from {_format_currency(current_value)}, the model estimates a "
                f"{_format_percent(loss_probability)} chance of finishing below today's value."
            ),
            html.P(
                "This is a probability model, not a forecast. It assumes the future behaves broadly like the recent return "
                "distribution and covariance structure, and it does not model trading, contributions, taxes, or regime changes."
            ),
        ],
        style={
            "padding": "14px",
            "border": "1px solid #e5e7eb",
            "borderRadius": "8px",
            "backgroundColor": "#f8fafc",
        },
    )


layout = html.Div(
    [
        dcc.Location(id="mc-location"),
        html.H2("Portfolio Monte Carlo Simulation", className="subtitle"),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Time horizon"),
                        dcc.Dropdown(
                            id="mc-years",
                            options=[
                                {"label": "1 year", "value": 1},
                                {"label": "3 years", "value": 3},
                                {"label": "5 years", "value": 5},
                            ],
                            value=DEFAULT_YEARS,
                            clearable=False,
                        ),
                    ],
                    style={"minWidth": "180px", "flex": "1"},
                ),
                html.Div(
                    [
                        html.Label("Simulation count"),
                        dcc.Dropdown(
                            id="mc-simulations",
                            options=[
                                {"label": "500", "value": 500},
                                {"label": "1,000", "value": 1000},
                                {"label": "5,000", "value": 5000},
                                {"label": "10,000", "value": 10000}
                            ],
                            value=DEFAULT_SIMULATIONS,
                            clearable=False,
                        ),
                    ],
                    style={"minWidth": "180px", "flex": "1"},
                ),
            ],
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"},
        ),
        html.Div(
            [
                _metric_card("Current Portfolio Value", "mc-current-value"),
                _metric_card("Median Ending Value", "mc-median-value"),
                _metric_card("5th Percentile", "mc-downside-value"),
                _metric_card("95th Percentile", "mc-upside-value"),
                _metric_card("Chance of Loss", "mc-loss-probability"),
                _metric_card("Median CAGR", "mc-cagr"),
            ],
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"},
        ),
        html.Div(id="mc-status", style={"marginBottom": "12px"}),
        dcc.Graph(id="mc-projection-chart"),
        dcc.Graph(id="mc-distribution-chart"),
        html.Div(id="mc-explanation"),
        dcc.Store(id="mc-price-cache")
       

    ]
)


if not hasattr(dash, "_monte_carlo_callback_registered"):
    dash._monte_carlo_callback_registered = True

    @dash.callback(
        Output("mc-price-cache", "data"),
        Input("mc-location", "pathname"),
    )
    def fetch_prices(_pathname):
        holdings = _load_holdings()
        if holdings.empty:
            return {"error": "No holdings found. Add positions on the Portfolio page first."}

        tickers = sorted(holdings["ticker"].dropna().unique().tolist())
        prices = _download_prices(tickers)
        if prices.empty:
            return {"error": "Unable to fetch enough price history to run the simulation."}

        prices = prices[[column for column in prices.columns if column in tickers]]
        prices = prices.dropna(axis=1, how="all")
        if prices.empty:
            return {"error": "Not enough clean price history after filtering missing data."}

        # Compute returns per ticker independently — don't require all tickers
        # to share the same dates. mean() and cov() handle NaN pairwise.
        returns = np.log(prices / prices.shift(1))
        returns = returns.dropna(axis=1, thresh=30)  # drop tickers with < 30 observations
        returns = returns.dropna(how="all")           # drop days where every ticker is NaN

        valid_tickers = returns.columns.tolist()
        if returns.empty or not valid_tickers:
            return {"error": "Return history is unavailable after filtering."}

        min_obs = int(returns.notna().sum().min())
        if min_obs < 30:
            return {"error": "Not enough clean price history after filtering missing data."}

        weights, current_value = _build_weights(holdings, valid_tickers)
        if weights.empty or current_value <= 0:
            return {"error": "Current portfolio value is zero, so the simulation cannot run."}

        dropped = sorted(set(tickers) - set(valid_tickers))
        return {
            "returns_json": returns.to_json(orient="split"),
            "weights_json": weights.to_json(orient="split"),
            "current_value": current_value,
            "valid_tickers": valid_tickers,
            "total_tickers": len(tickers),
            "min_obs": min_obs,
            "max_obs": int(returns.notna().sum().max()),
            "dropped": dropped,
            "error": None,
        }

    @dash.callback(
        Output("mc-status", "children"),
        Output("mc-projection-chart", "figure"),
        Output("mc-distribution-chart", "figure"),
        Output("mc-current-value", "children"),
        Output("mc-median-value", "children"),
        Output("mc-downside-value", "children"),
        Output("mc-upside-value", "children"),
        Output("mc-loss-probability", "children"),
        Output("mc-cagr", "children"),
        Output("mc-explanation", "children"),
        Input("mc-price-cache", "data"),
        Input("mc-years", "value"),
        Input("mc-simulations", "value"),
    )
    def update_monte_carlo(cache, years, simulations):
        empty_projection = _empty_figure("Projected Portfolio Value Paths", "No simulation data available.")
        empty_distribution = _empty_figure("Distribution of Ending Portfolio Values", "No simulation data available.")
        blank = ("--",) * 6

        if cache is None:
            return ("Loading...", empty_projection, empty_distribution, *blank, html.Div())

        error = cache.get("error")
        if error:
            return (error, empty_projection, empty_distribution, *blank, html.Div(error))

        returns = pd.read_json(cache["returns_json"], orient="split")
        weights = pd.read_json(cache["weights_json"], orient="split", typ="series")
        current_value = float(cache["current_value"])

        years_axis, path_values = _simulate_portfolio_paths(
            returns=returns,
            weights=weights,
            initial_value=current_value,
            years=int(years or DEFAULT_YEARS),
            simulations=int(simulations or DEFAULT_SIMULATIONS),
        )

        final_values = path_values[-1]
        median_value = float(np.percentile(final_values, 50))
        downside_value = float(np.percentile(final_values, 5))
        upside_value = float(np.percentile(final_values, 95))
        loss_probability = float(np.mean(final_values < current_value))
        median_cagr = float((median_value / current_value) ** (1 / max(int(years), 1)) - 1)

        n = len(cache["valid_tickers"])
        status_parts = [
            f"Using {n} of {cache['total_tickers']} holdings."
            f" Observations per ticker: {cache['min_obs']}–{cache['max_obs']} trading days.",
            f"Historical window: {LOOKBACK_PERIOD}.",
        ]
        if cache.get("dropped"):
            status_parts.append(f"Filtered due to missing price history: {', '.join(cache['dropped'])}.")

        return (
            " ".join(status_parts),
            _build_projection_chart(years_axis, path_values),
            _build_distribution_chart(final_values, current_value),
            _format_currency(current_value),
            _format_currency(median_value),
            _format_currency(downside_value),
            _format_currency(upside_value),
            _format_percent(loss_probability),
            _format_percent(median_cagr),
            _build_explanation(
                current_value=current_value,
                median_value=median_value,
                downside_value=downside_value,
                upside_value=upside_value,
                loss_probability=loss_probability,
                years=int(years or DEFAULT_YEARS),
                simulations=int(simulations or DEFAULT_SIMULATIONS),
            ),
        )
