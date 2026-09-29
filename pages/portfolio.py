import sqlite3
from datetime import datetime, timedelta, timezone

import dash
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from Services import insights, theme
from Services.components import metric_card
from Services.helper import load_data
from Services.ledger import account_summary, set_holding_type, transact, transaction_history
from Services.market import get_historical_prices
from Services.news import NewsFetchError, describe_fetch, fetch_portfolio_news
from Services.settings import get_settings
from Services.updater import update_prices

# Diverging fill for the map: rose (loss) -> neutral slate (flat) -> emerald (gain).
# Poles are deliberately darker than the theme accents so white tile labels stay readable.
PNL_COLORSCALE = [[0.0, "#be123c"], [0.5, "#273449"], [1.0, "#059669"]]
PNL_COLOR_LIMIT = 60  # +/- % at which the fill saturates


def make_portfolio_map(df):
    """Treemap: tile size = market value, tile colour = unrealized P&L %."""
    title = dict(
        text="Portfolio Map",
        subtitle=dict(
            text="Sized by market value · coloured by unrealized P&L",
            font=dict(color=theme.MUTED, size=13),
        ),
    )
    if df.empty or df["market_value_num"].sum() <= 0:
        fig = go.Figure()
        fig.add_annotation(
            text="No holdings yet", showarrow=False, font=dict(color=theme.MUTED, size=15)
        )
        fig.update_layout(title=title, xaxis={"visible": False}, yaxis={"visible": False})
        return fig

    d = df.copy()
    total = d["market_value_num"].sum()
    d["weight_pct"] = d["market_value_num"] / total * 100
    cost = d["avg_price_num"] * d["shares_num"]
    d["pnl_pct"] = (d["Total_Profit_Loss_num"] / cost * 100).where(cost > 0, 0.0)
    d = d.sort_values("market_value_num", ascending=False)

    fig = go.Figure(
        go.Treemap(
            labels=d["ticker"],
            parents=[""] * len(d),
            values=d["market_value_num"],
            branchvalues="total",
            text=[f"{v:+.0f}%" for v in d["pnl_pct"]],
            texttemplate="<b>%{label}</b><br>%{text}",
            textfont=dict(color=theme.TEXT_STRONG, size=14),
            textposition="middle center",
            customdata=d[
                [
                    "market_value_num",
                    "weight_pct",
                    "Total_Profit_Loss_num",
                    "pnl_pct",
                    "holding_type",
                ]
            ].values,
            hovertemplate=(
                "<b>%{label}</b> · %{customdata[4]}<br>"
                "$%{customdata[0]:,.0f} · %{customdata[1]:.1f}% of portfolio<br>"
                "P&L %{customdata[2]:+$,.0f} (%{customdata[3]:+.1f}%)"
                "<extra></extra>"
            ),
            marker=dict(
                colors=d["pnl_pct"],
                colorscale=PNL_COLORSCALE,
                cmin=-PNL_COLOR_LIMIT,
                cmid=0,
                cmax=PNL_COLOR_LIMIT,
                line=dict(width=2, color="rgba(2, 6, 23, 0.9)"),
                pad=dict(t=4, l=4, r=4, b=4),
                showscale=True,
                colorbar=dict(
                    orientation="h",
                    y=-0.02,
                    yanchor="top",
                    x=0.5,
                    thickness=8,
                    len=0.5,
                    ticksuffix="%",
                    tickvals=[-PNL_COLOR_LIMIT, 0, PNL_COLOR_LIMIT],
                    ticktext=[f"−{PNL_COLOR_LIMIT}%", "0%", f"+{PNL_COLOR_LIMIT}%"],
                    tickfont=dict(color=theme.MUTED, size=11),
                    outlinewidth=0,
                ),
            ),
            tiling=dict(pad=2),
        )
    )
    fig.update_layout(title=title, margin=dict(l=8, r=8, t=64, b=40))
    return fig


def make_holding_type_chart(df):
    if df.empty:
        grouped = pd.DataFrame(
            [{"holding_type": "No holdings", "market_value_num": 0.0, "percentage": 0.0}]
        )
        return px.bar(
            grouped,
            x="holding_type",
            y="percentage",
            title="Portfolio Allocation by Holding Type",
            color="holding_type",
        )

    grouped = df.groupby("holding_type", as_index=False)["market_value_num"].sum()
    total = grouped["market_value_num"].sum()
    if total > 0:
        grouped["percentage"] = grouped["market_value_num"] / total * 100
    else:
        grouped["percentage"] = 0.0
    fig = px.bar(
        grouped,
        x="holding_type",
        y="percentage",
        color="holding_type",
        color_discrete_map=theme.HOLDING_TYPE_COLORS,
        custom_data=["market_value_num"],
    )
    fig.update_traces(
        marker=dict(cornerradius=6, line=dict(width=0)),
        texttemplate="%{y:.0f}%",
        textposition="outside",
        textfont=dict(color=theme.TEXT, size=13),
        hovertemplate="<b>%{x}</b><br>%{y:.1f}% of portfolio · $%{customdata[0]:,.0f}<extra></extra>",
        showlegend=False,
    )

    targets = get_settings()["targets"]

    # One short target line per category, drawn in category coordinates
    # so it sits exactly over its bar regardless of chart width.
    categories = list(targets.keys())
    fig.update_xaxes(categoryorder="array", categoryarray=categories, title=None)
    for i, name in enumerate(categories):
        fig.add_shape(
            type="line",
            x0=i - 0.4,
            x1=i + 0.4,
            y0=targets[name],
            y1=targets[name],
            xref="x",
            yref="y",
            line=dict(color=theme.TEXT_STRONG, width=2, dash="dot"),
        )
    # legend entry for the target lines
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            line=dict(color=theme.TEXT_STRONG, width=2, dash="dot"),
            name="Target",
        )
    )

    fig.update_traces(width=0.55, selector={"type": "bar"})
    fig.update_layout(
        barmode="overlay",
        title=dict(
            text="Allocation by Holding Type",
            subtitle=dict(
                text="Current share vs "
                + " / ".join(f"{v}%" for v in targets.values())
                + " targets (dotted)",
                font=dict(color=theme.MUTED, size=13),
            ),
        ),
        legend=dict(title=None, orientation="h", x=1, xanchor="right", y=1.0, yanchor="bottom"),
        margin=dict(t=88),
    )
    fig.update_yaxes(range=[0, 100], ticksuffix="%", tickformat=".0f", title=None)
    return fig


def modify_portfolio(action, ticker, shares=None, avg_price=None, holding_type=None, fees=0):
    return transact(
        {"add": "buy", "remove": "sell"}.get(action, action),
        ticker=ticker,
        shares=shares,
        price=avg_price,
        holding_type=holding_type,
        fees=fees,
    )


dash.register_page(__name__, path="/portfolio", name="Portfolio", title="Portfolio", order=1)

TABLE_BORDER = "1px solid rgba(148, 163, 184, 0.14)"

layout = html.Div(
    [
        html.Div(
            [
                html.Div("Overview", className="page-eyebrow"),
                html.H2("Portfolio", className="page-title"),
                html.P(
                    "Holdings, allocation and the headlines that move them.",
                    className="page-subtitle",
                ),
            ],
            className="page-header",
        ),
        html.Div(
            [
                metric_card(label, "summary-" + key)
                for label, key in [
                    ("Account value", "nav"),
                    ("Invested holdings", "holdings"),
                    ("Cash", "cash"),
                    ("Unrealized P&L", "unrealized"),
                    ("Realized P&L since opening", "realized"),
                ]
            ],
            className="summary-grid",
        ),
        html.Div(id="portfolio-quote-status", className="data-status"),
        # Today's takeaways — what to look at first
        html.Div(
            [
                html.Div(
                    [
                        html.H3("Today's takeaways", className="card-title"),
                        html.Div(
                            [
                                html.Span(id="takeaways-stamp", className="muted"),
                                html.Button("Generate takeaways", id="takeaways-btn", n_clicks=0),
                            ],
                            className="toolbar",
                        ),
                    ],
                    className="card-header",
                ),
                dcc.Loading(
                    html.Div(
                        html.Div(
                            "Press Generate to analyse concentration, allocation drift, P&L outliers, "
                            "correlated positions and the latest headline.",
                            className="muted",
                        ),
                        id="takeaways-list",
                        className="takeaways",
                    ),
                    type="dot",
                    color=theme.ACCENT_BRIGHT,
                ),
            ],
            className="card",
        ),
        # Add / remove controls
        html.Div(
            [
                html.Div("Manage holdings", className="card-title"),
                html.Div(
                    [
                        dcc.Input(id="ticker-input", type="text", placeholder="Ticker (e.g. AAPL)"),
                        dcc.Input(
                            id="shares-input",
                            type="number",
                            placeholder="Shares",
                            min=0.000001,
                            step="any",
                        ),
                        dcc.Input(
                            id="avgprice-input",
                            type="number",
                            placeholder="Execution price",
                            min=0.000001,
                            step="any",
                        ),
                        # drop down for categorisation
                        dcc.Dropdown(
                            id="holding-type-input",
                            options=[
                                {"label": "Core Holding", "value": "Core"},
                                {"label": "High Conviction", "value": "High Conviction"},
                                {"label": "Moonshot", "value": "Moonshot"},
                            ],
                            placeholder="Holding type",
                            clearable=False,
                        ),
                        dcc.Input(
                            id="trade-fees",
                            type="number",
                            placeholder="Fees",
                            min=0,
                            value=0,
                            step="any",
                        ),
                        html.Button("Record Buy", id="add-btn", n_clicks=0),
                        html.Button(
                            "Record Sell", id="remove-btn", n_clicks=0, className="secondary"
                        ),
                        html.Button(
                            "Update type", id="type-btn", n_clicks=0, className="secondary"
                        ),
                        html.Button(
                            "Refresh quotes",
                            id="quote-refresh-btn",
                            n_clicks=0,
                            className="secondary",
                        ),
                    ],
                    className="toolbar",
                ),
                html.P(
                    "Record the execution price for buys and sells. Record available cash below before buying. Fractional shares are supported."
                ),
                html.Div(id="portfolio-action-status", role="status", **{"aria-live": "polite"}),
            ],
            className="card portfolio-controls",
        ),
        html.Div(
            [
                html.H3("Cash movements", className="card-title"),
                html.P(
                    "Opening cash is zero until you record your actual cash balance as a deposit. Past transactions are not inferred."
                ),
                html.Div(
                    [
                        dcc.Dropdown(
                            id="cash-kind",
                            options=[
                                {"label": k.title(), "value": k}
                                for k in ["deposit", "withdrawal", "dividend", "fee"]
                            ],
                            value="deposit",
                            clearable=False,
                        ),
                        dcc.Input(
                            id="cash-amount", type="number", placeholder="Amount", min=0, step="any"
                        ),
                        dcc.Input(
                            id="cash-note", type="text", placeholder="Note / dividend ticker"
                        ),
                        html.Button("Record cash movement", id="cash-btn", n_clicks=0),
                    ],
                    className="toolbar",
                ),
            ],
            className="card portfolio-controls",
        ),
        # Holdings table
        html.Div(
            [
                html.Div("Holdings", className="card-title"),
                dash_table.DataTable(
                    id="portfolio-table",
                    columns=[
                        {
                            "name": label,
                            "id": key,
                            "type": "numeric"
                            if key
                            in (
                                "shares",
                                "avg_price",
                                "current_price",
                                "market_value",
                                "Total_Profit_Loss",
                            )
                            else "text",
                            "format": {"specifier": ",.6~f" if key == "shares" else ",.2f"},
                        }
                        for key, label in [
                            ("ticker", "Ticker"),
                            ("shares", "Shares"),
                            ("avg_price", "Average cost"),
                            ("current_price", "Price"),
                            ("market_value", "Market value"),
                            ("Total_Profit_Loss", "Unrealized P&L"),
                            ("holding_type", "Holding type"),
                            ("quote_updated_at", "Quote time (UTC)"),
                        ]
                    ],
                    sort_action="native",
                    filter_action="native",
                    page_size=20,
                    data=[],
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "backgroundColor": "transparent",
                        "color": theme.TEXT,
                        "border": TABLE_BORDER,
                        "padding": "10px 12px",
                        "fontFamily": "Inter, Segoe UI, sans-serif",
                        "fontSize": "14px",
                        "textAlign": "left",
                    },
                    style_header={
                        "backgroundColor": "rgba(16, 185, 129, 0.14)",
                        "color": theme.TEXT_STRONG,
                        "fontWeight": "700",
                        "textTransform": "uppercase",
                        "fontSize": "12px",
                        "letterSpacing": "0.06em",
                        "border": TABLE_BORDER,
                    },
                    style_data_conditional=[
                        {
                            "if": {"row_index": "odd"},
                            "backgroundColor": "rgba(148, 163, 184, 0.04)",
                        },
                        {
                            "if": {"column_id": "ticker"},
                            "color": theme.ACCENT_BRIGHT,
                            "fontWeight": "700",
                        },
                        {
                            "if": {"column_id": "Total_Profit_Loss"},
                            "color": theme.POSITIVE,
                            "fontWeight": "600",
                        },
                        {
                            "if": {
                                "filter_query": "{Total_Profit_Loss} < 0",
                                "column_id": "Total_Profit_Loss",
                            },
                            "color": theme.NEGATIVE,
                        },
                        {
                            "if": {"filter_query": "{ticker} = 'TOTAL'"},
                            "fontWeight": "700",
                            "color": theme.TEXT_STRONG,
                            "backgroundColor": "rgba(16, 185, 129, 0.08)",
                            "borderTop": "1px solid rgba(52, 211, 153, 0.5)",
                        },
                    ],
                    css=[
                        {
                            "selector": ".dash-spreadsheet-inner *",
                            "rule": "background: transparent !important;",
                        }
                    ],
                ),
            ],
            className="card",
        ),
        html.Details(
            [
                html.Summary("Transaction history"),
                dash_table.DataTable(
                    id="transaction-table",
                    columns=[
                        {
                            "name": k.replace("_", " ").title(),
                            "id": k,
                            "type": "numeric"
                            if k in ("shares", "price", "amount", "fees", "realized_pnl")
                            else "text",
                        }
                        for k in [
                            "timestamp",
                            "kind",
                            "ticker",
                            "shares",
                            "price",
                            "amount",
                            "fees",
                            "realized_pnl",
                            "note",
                        ]
                    ],
                    data=[],
                    sort_action="native",
                    filter_action="native",
                    page_size=15,
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "backgroundColor": "#111a2e",
                        "color": theme.TEXT,
                        "textAlign": "left",
                    },
                ),
            ],
            className="card",
        ),
        # Charts
        html.Div(
            [
                html.Div(dcc.Graph(id="value-chart"), className="card"),
                html.Div(dcc.Graph(id="holding-type-chart"), className="card"),
            ],
            className="section-grid two",
        ),
        # Rebalance actions — allocation drift turned into trades
        html.Div(
            [
                html.Div(
                    [
                        html.H3("Rebalance actions", className="card-title"),
                        html.Span(
                            id="portfolio-target-label",
                            className="muted",
                        ),
                    ],
                    className="card-header",
                ),
                html.Div(id="rebalance-rows", className="rebalance"),
            ],
            className="card",
        ),
        dcc.Interval(
            id="interval-component",
            interval=60 * 1000,
            n_intervals=0,
        ),
        # Stock news section
        html.Div(
            [
                html.Div(
                    [
                        html.H3("Stock News", className="card-title"),
                        html.Button(
                            "Refresh News",
                            id="portfolio-news-btn",
                            n_clicks=0,
                            className="secondary",
                        ),
                    ],
                    className="card-header",
                ),
                html.Div(
                    id="portfolio-inline-news-status",
                    className="muted",
                    style={"marginBottom": "12px"},
                ),
                html.Div(id="portfolio-inline-news-feed", className="news-feed"),
            ],
            className="card",
        ),
        dcc.Store(id="portfolio-inline-news-data"),
    ]
)


@dash.callback(
    Output("portfolio-table", "data"),
    Output("value-chart", "figure"),
    Output("holding-type-chart", "figure"),
    Output("portfolio-action-status", "children"),
    Output("portfolio-quote-status", "children"),
    *[
        Output("summary-" + k, "children")
        for k in ("nav", "holdings", "cash", "unrealized", "realized")
    ],
    Output("transaction-table", "data"),
    Output("portfolio-target-label", "children"),
    Input("add-btn", "n_clicks"),
    Input("remove-btn", "n_clicks"),
    Input("type-btn", "n_clicks"),
    Input("quote-refresh-btn", "n_clicks"),
    Input("cash-btn", "n_clicks"),
    Input("interval-component", "n_intervals"),
    Input("settings-version", "data"),
    State("ticker-input", "value"),
    State("shares-input", "value"),
    State("avgprice-input", "value"),
    State("holding-type-input", "value"),
    State("trade-fees", "value"),
    State("cash-kind", "value"),
    State("cash-amount", "value"),
    State("cash-note", "value"),
)
def modify_data(
    _add,
    _sell,
    _type,
    _refresh,
    _cash,
    _interval,
    _settings,
    ticker,
    shares,
    price,
    holding_type,
    fees,
    cash_kind,
    cash_amount,
    cash_note,
):
    trigger = dash.ctx.triggered_id
    message = ""
    try:
        if trigger in ("add-btn", "remove-btn"):
            message = modify_portfolio(
                "add" if trigger == "add-btn" else "remove",
                ticker,
                shares,
                price,
                holding_type,
                fees,
            )
        elif trigger == "type-btn":
            message = set_holding_type(ticker, holding_type)
        elif trigger == "cash-btn":
            message = transact(cash_kind, amount=cash_amount, note=cash_note)
        elif trigger in ("quote-refresh-btn", "interval-component"):
            message = update_prices(force=trigger == "quote-refresh-btn")
    except (ValueError, sqlite3.Error) as exc:
        message = f"Not saved: {exc}"
    df = load_data()
    chart = insights.prepare_holdings(df).rename(
        columns={
            "market_value": "market_value_num",
            "shares": "shares_num",
            "avg_price": "avg_price_num",
            "Total_Profit_Loss": "Total_Profit_Loss_num",
        }
    )
    summary = account_summary()
    stamps = pd.to_datetime(df.quote_updated_at, utc=True, errors="coerce")
    stale = df.loc[
        stamps.isna() | ((pd.Timestamp.now(tz="UTC") - stamps) > pd.Timedelta(minutes=15)), "ticker"
    ].tolist()
    status = "Quote timestamps are market observation times, not edit times. "
    status += (
        ("Older than 15 minutes or unverified: " + ", ".join(stale) + ". Markets may be closed.")
        if stale
        else "All quotes are within 15 minutes."
    )
    targets = get_settings()["targets"]
    return (
        df.to_dict("records"),
        make_portfolio_map(chart),
        make_holding_type_chart(chart),
        message,
        status,
        *[f"${summary[k]:,.2f}" for k in ("nav", "holdings", "cash", "unrealized", "realized")],
        transaction_history().to_dict("records"),
        "Targets: " + " / ".join(f"{k} {v:g}%" for k, v in targets.items()),
    )


if not hasattr(dash, "_portfolio_inline_news_registered"):
    dash._portfolio_inline_news_registered = True

    from datetime import datetime, timezone

    def _serialize(article):
        a = dict(article)
        if isinstance(a.get("published_at"), datetime):
            a["published_at"] = a["published_at"].isoformat()
        return a

    def _deserialize(article):
        a = dict(article)
        if isinstance(a.get("published_at"), str):
            a["published_at"] = datetime.fromisoformat(a["published_at"])
        return a

    def _label(score):
        if score >= 7:
            return "High impact"
        if score >= 3:
            return "Watch"
        return "Latest"

    def _relative_time(published_at):
        delta = datetime.now(timezone.utc) - published_at
        hours = max(int(delta.total_seconds() // 3600), 0)
        if hours < 1:
            return "< 1h ago"
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"

    def _inline_news_card(article):
        label = _label(article.get("importance_score", 0))
        pub = article["published_at"]
        return html.Div(
            [
                html.Div(
                    [
                        html.Span(article["ticker"], className="news-ticker"),
                        html.Span(
                            label,
                            className=f"news-impact news-impact-{label.lower().replace(' ', '-')}",
                        ),
                    ],
                    className="news-card-topline",
                ),
                html.A(
                    article["title"],
                    href=article["url"],
                    target="_blank",
                    rel="noreferrer",
                    className="news-title",
                ),
                html.Div(
                    [html.Span(article["source"]), html.Span(_relative_time(pub))],
                    className="news-meta",
                ),
                html.P(article.get("description") or "", className="news-description"),
                html.Div(
                    html.A(
                        "Read →",
                        href=article["url"],
                        target="_blank",
                        rel="noreferrer",
                        className="news-action",
                    ),
                    className="news-card-footer",
                ),
            ],
            className="news-card",
        )

    @dash.callback(
        Output("portfolio-inline-news-data", "data"),
        Output("portfolio-inline-news-status", "children"),
        Input("portfolio-news-btn", "n_clicks"),
    )
    def fetch_inline_news(n_clicks):
        holdings = load_data()
        if holdings.empty:
            return [], "No holdings found."
        tickers = holdings["ticker"].dropna().astype(str).str.strip().str.upper().tolist()
        tickers = [t for t in tickers if t]
        if not tickers:
            return [], "No holdings found."
        # Page load is served from cache when fresh; the button forces a live fetch.
        force = dash.ctx.triggered_id == "portfolio-news-btn"
        try:
            articles = fetch_portfolio_news(tickers, per_ticker=5, max_items=9, force=force)
        except NewsFetchError as exc:
            return [], f"Could not fetch news: {exc}"
        if not articles:
            return [], f"No recent news found for your holdings. {describe_fetch()}"
        status = f"{len(articles)} recent headlines across {len({a['ticker'] for a in articles})} holdings. {describe_fetch()}"
        return [_serialize(a) for a in articles], status

    # --- Rebalance + takeaways -------------------------------------------

    def _rebalance_row(row):
        fill_width = f"{min(row['current_pct'], 100):.1f}%"
        return html.Div(
            [
                html.Div(row["bucket"], className="rebalance-bucket"),
                html.Div(
                    [
                        html.Div(
                            className=f"rebalance-bar-fill {row['status']}",
                            style={"width": fill_width},
                        ),
                        html.Div(
                            className="rebalance-bar-target",
                            style={"left": f"{row['target_pct']}%"},
                        ),
                    ],
                    className="rebalance-bar",
                ),
                html.Div(
                    f"{row['current_pct']:.0f}% now · {row['target_pct']}% target",
                    className="rebalance-numbers muted",
                ),
                html.Span(row["action"], className=f"action-chip action-{row['status']}"),
            ],
            className="rebalance-row",
        )

    def _takeaway(level, text):
        return html.Div(
            [html.Span(className=f"takeaway-dot level-{level}"), html.Span(text)],
            className="takeaway",
        )

    # Correlation needs a price download; keep it for 15 minutes per ticker set.
    _corr_cache = {"key": None, "pairs": [], "at": None}

    def _correlated_pairs_cached(tickers):
        key = tuple(sorted(set(tickers)))
        now = datetime.now(timezone.utc)
        if (
            _corr_cache["key"] == key
            and _corr_cache["at"]
            and now - _corr_cache["at"] < timedelta(minutes=15)
        ):
            return _corr_cache["pairs"]
        try:
            prices = get_historical_prices(list(key), period="6mo")
            pairs = (
                insights.correlated_pairs(prices.pct_change(fill_method=None).dropna())
                if not prices.empty
                else []
            )
        except Exception:
            pairs = []
        _corr_cache.update(key=key, pairs=pairs, at=now)
        return pairs

    def _top_headline(tickers):
        try:
            articles = fetch_portfolio_news(tickers, per_ticker=1, max_items=1)
        except NewsFetchError:
            return None
        return articles[0] if articles else None

    @dash.callback(
        Output("rebalance-rows", "children"),
        Input("portfolio-table", "data"),
    )
    def render_rebalance(_table_data):
        holdings = insights.prepare_holdings(load_data())
        return [_rebalance_row(row) for row in insights.rebalance_plan(holdings)]

    # Generated on demand (button) rather than on every table refresh, so the
    # card reads as an analysis step the user triggers.
    @dash.callback(
        Output("takeaways-list", "children"),
        Output("takeaways-stamp", "children"),
        Input("takeaways-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def render_takeaways(_n_clicks):
        holdings = insights.prepare_holdings(load_data())
        rows = insights.rebalance_plan(holdings)
        tickers = holdings["ticker"].tolist()
        pairs = _correlated_pairs_cached(tickers) if tickers else []
        headline = _top_headline(tickers) if tickers else None
        items = insights.takeaways(holdings, rows, pairs, headline)
        return [
            _takeaway(level, text) for level, text in items
        ], f"Generated {datetime.now():%H:%M}"

    @dash.callback(
        Output("portfolio-inline-news-feed", "children"),
        Input("portfolio-inline-news-data", "data"),
    )
    def render_inline_news(data):
        articles = [_deserialize(a) for a in (data or [])]
        if not articles:
            return html.Div(
                "Click 'Refresh News' to load the latest headlines for your holdings.",
                className="muted",
                style={"padding": "12px 0"},
            )
        return [_inline_news_card(a) for a in articles]
