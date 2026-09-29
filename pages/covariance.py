import dash
import numpy as np
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html

from Services.components import metric_card as _metric_card
from Services.helper import load_data
from Services.market import clean_returns, coverage_text, get_historical_prices
from Services.performance import risk_contributions, valid_covariance
from Services.settings import get_settings

dash.register_page(__name__, path="/covariance", name="Correlations", title="Correlations", order=3)

layout = html.Div(
    [
        dcc.Location(id="cov_location"),
        html.H2("Correlations", className="page-title"),
        html.Div(
            [
                _metric_card(label, key)
                for label, key in [
                    ("Portfolio annualized volatility", "covariance-metric-portfolio-vol"),
                    ("Benchmark volatility", "covariance-metric-spy-vol"),
                    ("Diversification ratio", "covariance-metric-div-ratio"),
                ]
            ],
            className="summary-grid",
        ),
        html.Div(id="covariance-status", className="data-status"),
        dcc.Graph(id="covariance-heatmap"),
        html.Div(id="covariance-insights", className="panel"),
        dcc.Graph(id="risk-contribution-chart"),
        html.P(
            "Risk contribution is each holding's share of modeled portfolio variance, using current invested weights. "
            "A negative contribution can indicate a diversifying position. Cash is excluded."
        ),
        html.Div(
            [
                html.H3("Scenario analysis"),
                html.Label("Broad market shock (%)"),
                dcc.Slider(
                    -60,
                    30,
                    5,
                    value=-20,
                    id="scenario-market",
                    tooltip={"placement": "bottom", "always_visible": True},
                ),
                html.Label("Holding-type shock (%)"),
                dcc.Slider(
                    -80,
                    30,
                    5,
                    value=-30,
                    id="scenario-bucket-shock",
                    tooltip={"placement": "bottom", "always_visible": True},
                ),
                dcc.Dropdown(
                    id="scenario-bucket",
                    options=[
                        {"label": k, "value": k} for k in ["Core", "High Conviction", "Moonshot"]
                    ],
                    value="Moonshot",
                    clearable=False,
                ),
                html.Div(id="scenario-results", className="data-status"),
                html.P(
                    "These are separate hypothetical shocks, not probabilities. Market impact uses historical beta; "
                    "holding-type impact applies the chosen percentage directly. Correlations and beta can change in a crisis."
                ),
            ],
            className="card portfolio-controls",
        ),
        dcc.Store(id="risk-sample"),
    ]
)


@dash.callback(
    Output("covariance-status", "children"),
    Output("covariance-heatmap", "figure"),
    Output("covariance-insights", "children"),
    Output("covariance-metric-portfolio-vol", "children"),
    Output("covariance-metric-spy-vol", "children"),
    Output("covariance-metric-div-ratio", "children"),
    Output("risk-contribution-chart", "figure"),
    Output("risk-sample", "data"),
    Input("cov_location", "pathname"),
    Input("analysis-period", "value"),
    Input("analysis-benchmark", "value"),
    Input("settings-version", "data"),
)
def refresh_covariance(_pathname, period="1y", benchmark="SPY", _version=None):
    def empty(message):
        return message, px.line(), "", "N/A", "N/A", "N/A", px.line(), None

    holdings = load_data()
    if holdings.empty or holdings.market_value.sum() <= 0:
        return empty("No invested holdings.")
    prices = get_historical_prices(holdings.ticker.tolist() + [benchmark], period)
    if prices.empty:
        return empty("Historical prices are unavailable.")
    returns = clean_returns(prices.reindex(columns=holdings.ticker.tolist()))
    bench = (
        prices[benchmark].pct_change(fill_method=None).dropna()
        if benchmark in prices
        else pd.Series(dtype=float)
    )
    if not bench.empty:
        common = returns.index.intersection(bench.index)
        returns, bench = returns.loc[common], bench.loc[common]
    status = coverage_text(holdings, returns, period, benchmark)
    if len(returns) < 30 or returns.shape[1] == 0:
        return empty(status + " At least 30 complete common observations are required.")
    values = holdings.set_index("ticker").market_value.reindex(returns.columns)
    weights = values / values.sum()
    cov = valid_covariance(returns)
    w = weights.to_numpy()
    variance = float(w @ cov @ w)
    volatility = np.sqrt(variance * 252)
    avg_vol = float(w @ np.sqrt(np.diag(cov) * 252))
    ratio = avg_vol / volatility if volatility > 0 else None
    corr = returns.corr()
    fig = px.imshow(
        corr,
        zmin=-1,
        zmax=1,
        color_continuous_scale="RdBu",
        title=f"Daily-return correlations ({period})",
        labels={"color": "Correlation"},
    )
    contributions = risk_contributions(returns, weights) * 100
    contribution_fig = px.bar(
        x=contributions.index,
        y=contributions.values,
        labels={"x": "Holding", "y": "Share of portfolio variance (%)"},
        title="Which holdings drive portfolio risk?",
    )
    settings = get_settings()
    top = weights.idxmax()
    explanation = [
        html.P(
            f"Largest modeled holding: {top} ({weights[top]:.1%}). Concentration limit: {settings['concentration']:g}%."
        )
    ]
    if weights[top] * 100 > settings["concentration"]:
        explanation.append(html.P("This holding exceeds your configured concentration limit."))
    pairs = [
        (a, b, float(corr.loc[a, b]))
        for i, a in enumerate(corr)
        for b in corr.columns[i + 1 :]
        if pd.notna(corr.loc[a, b])
    ]
    strong = sorted([p for p in pairs if abs(p[2]) >= 0.7], key=lambda p: abs(p[2]), reverse=True)[
        :5
    ]
    explanation.append(
        html.Ul(
            [
                html.Li(f"{a} / {b}: {v:.2f} ({'move together' if v > 0 else 'tend to offset'}).")
                for a, b, v in strong
            ]
        )
        if strong
        else html.P("No pair has absolute correlation of at least 0.70 in this sample.")
    )
    explanation.append(
        html.P(
            "Diversification ratio = weighted average individual volatility / portfolio volatility. It describes this sample, not a guarantee about future diversification."
        )
    )
    portfolio = returns @ weights
    beta = (
        float(portfolio.cov(bench) / bench.var())
        if len(bench) > 1 and bench.var() > 1e-20
        else None
    )
    payload = {
        "beta": beta,
        "modeled_value": float(values.sum()),
        "coverage": float(values.sum() / holdings.market_value.sum()),
        "buckets": holdings.groupby("holding_type").market_value.sum().to_dict(),
    }
    return (
        status,
        fig,
        explanation,
        f"{volatility:.2%}",
        f"{bench.std() * np.sqrt(252):.2%}" if len(bench) > 1 else "N/A",
        f"{ratio:.2f}" if ratio is not None else "N/A",
        contribution_fig,
        payload,
    )


@dash.callback(
    Output("scenario-results", "children"),
    Input("risk-sample", "data"),
    Input("scenario-market", "value"),
    Input("scenario-bucket-shock", "value"),
    Input("scenario-bucket", "value"),
)
def scenario_results(sample, market_shock, bucket_shock, bucket):
    if not sample:
        return "Load a valid risk sample to calculate scenarios."
    if not (-60 <= float(market_shock) <= 30 and -80 <= float(bucket_shock) <= 30):
        return "Choose shocks within the displayed ranges."
    beta = sample.get("beta")
    market = (
        "Market scenario unavailable without benchmark data."
        if beta is None
        else f"Market scenario: {beta * market_shock / 100 * sample['modeled_value']:+,.2f} USD on modeled holdings (beta {beta:.2f}; {sample['coverage']:.1%} value coverage)."
    )
    bucket_value = sample["buckets"].get(bucket, 0)
    return [
        html.P(market),
        html.P(
            f"Separate {bucket} scenario: {bucket_value * bucket_shock / 100:+,.2f} USD on ${bucket_value:,.2f} of holdings."
        ),
    ]
