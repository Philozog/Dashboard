from dash import dcc, html, dash_table
import dash
from dash.dependencies import Input, Output, State

import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go

from Services.updater import update_prices
from Services.helper import load_data
from Services.database import DB_PATH
from Services.news import fetch_portfolio_news


def make_big_pie(df):
    if df.empty:
        return px.pie(
            pd.DataFrame([{"ticker": "No holdings", "market_value_num": 1}]),
            values="market_value_num",
            names="ticker",
            title="Portfolio Market Value Distribution",
        )
    fig=px.pie(df,values="market_value_num",names="ticker",title="Portfolio Market Value Distribution",color_discrete_sequence=px.colors.sequential.Purples_r)
    fig.update_traces(textposition='inside', textinfo='percent+label')
    fig.update_layout(title={"text":"Portfolio Market Value Distribution","x":0.5,"xanchor":"center","y":0.95})
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

        grouped = (
            df.groupby("holding_type", as_index=False)["market_value_num"]
            .sum()
        )
        total = grouped["market_value_num"].sum()
        if total > 0:
            grouped["percentage"] = grouped["market_value_num"] / total * 100
        else:
            grouped["percentage"] = 0.0
        fig = px.bar(
            grouped,
            x="holding_type",
            y="percentage",
            title="Portfolio Allocation by Holding Type",
            color="holding_type",
            color_discrete_map={
                "Core": "#4CAF50",
                "High Conviction": "#FFC107",
                "Moonshot": "#F44336",
            },
        )

        targets={
            "Core": 60,
            "High Conviction": 30,
            "Moonshot": 10}
        
        fig.add_trace(go.Scatter(
            x=list(targets.keys()),
            y=list(targets.values()),
            mode="markers",
            marker=dict(color="red", size=258, symbol="line-ew",line=dict(width=2)),name="Target"))


   
        fig.update_yaxes(range=[0, 100], ticksuffix="%",tickformat=".0f")

        fig.update_yaxes(ticksuffix="%", separatethousands=True)
        return fig


def modify_portfolio(action, ticker, shares=None, avg_price=None, holding_type=None):
    if not ticker:
        raise ValueError("Ticker is required.")

    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("Ticker is required.")

    if action not in {"add", "remove"}:
        raise ValueError("Invalid action supplied.")

    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        existing_rows = conn.execute(
            "SELECT rowid AS _rowid, * FROM portfolio WHERE ticker = ? ORDER BY rowid",
            (ticker,),
        ).fetchall()
        existing = existing_rows[0] if existing_rows else None
        existing_rowids = [row["_rowid"] for row in existing_rows]
        primary_rowid = existing_rowids[0] if existing_rowids else None

        def _existing_shares():
            return sum(_to_float(row["shares"]) for row in existing_rows)

        def _existing_avg_price():
            total_shares = _existing_shares()
            if total_shares <= 0:
                return _to_float(existing["avg_price"]) if existing else 0.0

            weighted_cost = sum(
                _to_float(row["avg_price"]) * _to_float(row["shares"])
                for row in existing_rows
            )
            return weighted_cost / total_shares

        def _delete_duplicate_rows():
            for duplicate_rowid in existing_rowids[1:]:
                conn.execute("DELETE FROM portfolio WHERE rowid = ?", (duplicate_rowid,))

        if action == "add":
            if shares is None or avg_price is None or holding_type is None:
                raise ValueError("Shares, average price, and holding type are required to add a ticker.")

            shares = float(shares)
            avg_price = float(avg_price)
            current_shares = _existing_shares()
            new_shares = current_shares + shares
            if current_shares > 0:
                existing_avg_price = _existing_avg_price()
                avg_price = (
                    (existing_avg_price * current_shares) + (avg_price * shares)
                ) / new_shares

            current_price = _to_float(existing["current_price"]) if existing else 0.0
            price_basis = current_price if current_price else avg_price
            market_value = price_basis * new_shares
            total_profit_loss = (current_price - avg_price) * new_shares if current_price else 0.0
            timestamp = pd.Timestamp.now().isoformat()

            if existing:
                conn.execute(
                    """
                    UPDATE portfolio
                    SET shares = ?, avg_price = ?, market_value = ?,
                        Total_Profit_Loss = ?, last_updated = ?, holding_type=?
                    WHERE rowid = ?
                    """,
                    (new_shares, avg_price, market_value,total_profit_loss, timestamp, holding_type, primary_rowid),
                )
                _delete_duplicate_rows()
            else:
                conn.execute(
                    """
                    INSERT INTO portfolio (ticker, shares, avg_price, current_price,
                    market_value, Total_Profit_Loss, holding_type, last_updated
                                        )
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                                    """,
                        (
                            ticker,
                            new_shares,
                            avg_price,
                            current_price,
                            market_value,
                            total_profit_loss,
                            holding_type,
                            timestamp,
                        ),
                    )

        elif action == "remove":
            if not existing:
                raise ValueError("Ticker not found in portfolio.")
            if shares is None:
                raise ValueError("Shares are required when removing a ticker.")

            current_shares = _existing_shares()
            new_shares = current_shares - float(shares)

            if new_shares <= 0:
                conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
            else:
                avg_price_existing = _existing_avg_price()
                current_price = _to_float(existing["current_price"])
                price_basis = current_price if current_price else avg_price_existing
                market_value = price_basis * new_shares
                total_profit_loss = (
                    (current_price - avg_price_existing) * new_shares if current_price else 0.0
                )
                timestamp = pd.Timestamp.now().isoformat()

                conn.execute(
                    """
                    UPDATE portfolio
                    SET shares = ?, market_value = ?, Total_Profit_Loss = ?, last_updated = ?
                WHERE rowid = ?
                                """,
                        (
                            new_shares,
                            market_value,
                            total_profit_loss,
                            timestamp,
                            primary_rowid,
                        ),
                                        )
                _delete_duplicate_rows()


dash.register_page(__name__, path="/", name="Portfolio", title="Portfolio")
layout = html.Div([
    
    html.Div([
        dcc.Input(id="ticker-input", type="text", placeholder="Ticker (e.g. AAPL)"),
        dcc.Input(id="shares-input", type="number", placeholder="Shares", min=1),
        dcc.Input(id="avgprice-input", type="number", placeholder="Price", min=0),
        html.Button("Add Ticker", id="add-btn", n_clicks=0, style={"marginRight": "10px"}),
        html.Button("Remove Ticker", id="remove-btn", n_clicks=0)]),
        
        #drop down for categorisation
        dcc.Dropdown(
        id="holding-type-input",
        options=[
            {"label": "Core Holding", "value": "Core"},
            {"label": "High Conviction", "value": "High Conviction"},
            {"label": "Moonshot", "value": "Moonshot"},
        ],
        placeholder="Holding type",
        clearable=False,
        style={"width": "200px", "marginRight": "10px"}
    ),



    dash_table.DataTable(
        id="portfolio-table",
        hidden_columns=["id"],
        columns=[{"name": i, "id": i, "type": "text"} for i in load_data().columns],
        data=[],
        style_data_conditional=[{"if": {"filter_query": "{ticker} = 'TOTAL'"},
                                    "fontWeight": "bold",
                                    "backgroundColor": "#f7f8fc"}],
                                    
    style_header={"backgroundColor":"#EA84FC","fontWeight": "bold","color":'black'}

    ),
    dcc.Graph(id="value-chart"),
    dcc.Graph(id="holding-type-chart"),
    dcc.Interval(
        id="interval-component",
        interval=60 * 1000,
        n_intervals=0,
    ),

    # Stock news section
    html.Hr(style={"margin": "28px 0 20px"}),
    html.Div(
        [
            html.H3("Stock News", style={"margin": "0", "fontSize": "18px"}),
            html.Button("Refresh News", id="portfolio-news-btn", n_clicks=0),
        ],
        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"},
    ),
    html.Div(id="portfolio-inline-news-status", style={"fontSize": "13px", "color": "#64748b", "marginBottom": "12px"}),
    html.Div(id="portfolio-inline-news-feed", className="news-feed"),
    dcc.Store(id="portfolio-inline-news-data"),
])


@dash.callback(
    Output("portfolio-table", "data"),
    Output("value-chart", "figure"),
    Output("holding-type-chart", "figure"),
    Input("add-btn", "n_clicks"),
    Input("remove-btn", "n_clicks"),
    Input("interval-component", "n_intervals"),
    State("ticker-input", "value"),
    State("shares-input", "value"),
    State("avgprice-input", "value"),
    State("holding-type-input", "value"),

)
def modify_data(add_clicks, remove_clicks, n_intervals, ticker, shares, avg_price, holding_type):
    from dash import callback_context

    ctx = callback_context
    button_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

    try:
        if button_id == "add-btn" and ticker and shares is not None and avg_price is not None and holding_type is not None:
            modify_portfolio("add", ticker, shares, avg_price,holding_type)
        elif button_id == "remove-btn" and ticker and shares is not None:
            modify_portfolio("remove", ticker, shares)
    except ValueError:
        pass

    if button_id == "interval-component" and n_intervals:
        try:
            update_prices()
        except Exception:
            pass

    df = load_data()
    if df.empty:
        table_df = pd.DataFrame(
            [
                {
                    "id": "",
                    "ticker": "TOTAL",
                    "shares": "",
                    "avg_price": "",
                    "current_price": "",
                    "market_value": "0",
                    "last_updated": "",
                    "Total_Profit_Loss": "0.00",
                    "holding_type": "",
                }
            ]
        )
        return (
            table_df[load_data().columns].to_dict("records"),
            make_big_pie(pd.DataFrame(columns=["ticker", "market_value_num"])),
            make_holding_type_chart(pd.DataFrame(columns=["holding_type", "market_value_num"])),
        )

    df["market_value_num"] = pd.to_numeric(df["market_value"], errors="coerce").fillna(0)
    df["shares_num"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
    df["avg_price_num"] = pd.to_numeric(df["avg_price"], errors="coerce").fillna(0)
    df["current_price"] = pd.to_numeric(df["current_price"], errors="coerce").fillna(0)
    df["Total_Profit_Loss_num"] = pd.to_numeric(df["Total_Profit_Loss"], errors="coerce").fillna(0)
    if "holding_type" not in df.columns:
        df["holding_type"] = ""
    df["holding_type"] = df["holding_type"].fillna("Unassigned")
    df["shares"] = df["shares_num"].apply(lambda x: f"{x:,.0f}" if x.is_integer() else f"{x:,.4f}")
    df["avg_price"] = df["avg_price_num"].apply(lambda x: f"{x:,.2f}")
    df["current_price"] = df["current_price"].apply(lambda x: f"{x:,.2f}")
    df["market_value"] = df["market_value_num"].apply(lambda x: f"{x:,.0f}")
    df["Total_Profit_Loss"] = df["Total_Profit_Loss_num"].apply(lambda x: f"{x:,.2f}")
    last_row = pd.DataFrame([{
        "id": "",
        "ticker": "TOTAL",
        "shares": "",
        "avg_price": "",
        "current_price": "",
        "market_value": f"{df['market_value_num'].sum():,.0f}",
        "last_updated": "",
        "Total_Profit_Loss": f"{df['Total_Profit_Loss_num'].sum():,.0f}",
        "holding_type": ""
    }])
    df= df[df["ticker"] != "TOTAL"]
    df = pd.concat([df, last_row], ignore_index=True)
    df_chart = df[df["ticker"] != "TOTAL"]
    chart_fig = make_big_pie(df_chart)
    holding_fig= make_holding_type_chart(df_chart)
    table_data = df.to_dict("records")
    return table_data, chart_fig, holding_fig


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
                        html.Span(label, className=f"news-impact news-impact-{label.lower().replace(' ', '-')}"),
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
                    html.A("Read →", href=article["url"], target="_blank", rel="noreferrer", className="news-action"),
                    className="news-card-footer",
                ),
            ],
            className="news-card",
        )

    @dash.callback(
        Output("portfolio-inline-news-data", "data"),
        Output("portfolio-inline-news-status", "children"),
        Input("portfolio-news-btn", "n_clicks"),
        Input("interval-component", "n_intervals"),
    )
    def fetch_inline_news(n_clicks, n_intervals):
        holdings = load_data()
        if holdings.empty:
            return [], "No holdings found."
        tickers = (
            holdings["ticker"].dropna().astype(str).str.strip().str.upper().tolist()
        )
        tickers = [t for t in tickers if t]
        if not tickers:
            return [], "No holdings found."
        try:
            articles = fetch_portfolio_news(tickers, per_ticker=5, max_items=9)
        except Exception:
            return [], "Could not fetch news right now — check your NEWS_API_KEY."
        if not articles:
            return [], "No recent news found for your holdings."
        status = f"{len(articles)} recent headlines across {len({a['ticker'] for a in articles})} holdings."
        return [_serialize(a) for a in articles], status

    @dash.callback(
        Output("portfolio-inline-news-feed", "children"),
        Input("portfolio-inline-news-data", "data"),
    )
    def render_inline_news(data):
        articles = [_deserialize(a) for a in (data or [])]
        if not articles:
            return html.Div(
                "Click 'Refresh News' to load the latest headlines for your holdings.",
                style={"color": "#94a3b8", "padding": "12px 0"},
            )
        return [_inline_news_card(a) for a in articles]
