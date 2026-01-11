from dash import dcc, html, dash_table
import dash
from dash.dependencies import Input, Output, State

import pandas as pd
import sqlite3
import plotly.express as px
import yfinance as yf

from Services.updater import update_prices
from Services.helper import load_data



DB_PATH = "portfolio.db"




def make_big_pie(df):
    fig=px.pie(df,values="market_value_num",names="ticker",title="Portfolio Market Value Distribution",color_discrete_sequence=px.colors.sequential.Purples_r)
    fig.update_traces(textposition='inside', textinfo='percent+label')
    fig.update_layout(title={"text":"Portfolio Market Value Distribution","x":0.5,"xanchor":"center","y":0.95})
    return fig




def make_portfolio_chart(df):
        fig = px.bar(
            df,
            x="ticker",
            y="market_value_num",
            title="Portfolio Market Value Distribution",
            text="Total_Profit_Loss_num",
        )
        fig.update_traces(
            marker_color="#B884FC",
            textposition="none",
        )

        fig.update_layout(
            template="seaborn",
            title_font=dict(size=26, family="Arial", color="#333"),
            xaxis_title="Ticker",
            yaxis_title="Market Value ($)",
            yaxis=dict(showgrid=False, gridcolor="white", zeroline=False),
            paper_bgcolor="white",
            height=250,
            margin=dict(l=50, r=30, t=80, b=40),
        )

        fig.update_yaxes(tickprefix="$", separatethousands=True)
        return fig


def make_holding_type_chart(df):
        grouped = (
            df.groupby("holding_type", as_index=False)["market_value_num"]
            .sum()
        )
        total = grouped["market_value_num"].sum()
        grouped["percentage"] = grouped["market_value_num"] / total * 100
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
        fig.update_yaxes(range=[0, 100], ticksuffix="%")

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
        existing = conn.execute(
            "SELECT * FROM portfolio WHERE ticker = ?", (ticker,)
        ).fetchone()

        if action == "add":
            if shares is None or avg_price is None or holding_type is None:
                raise ValueError("Shares, average price, and holding type are required to add a ticker.")

            shares = float(shares)
            avg_price = float(avg_price)
            current_price = _to_float(existing["current_price"]) if existing else 0.0
            price_basis = current_price if current_price else avg_price
            market_value = price_basis * shares
            total_profit_loss = (current_price - avg_price) * shares if current_price else 0.0
            timestamp = pd.Timestamp.now().isoformat()

            if existing:
                conn.execute(
                    """
                    UPDATE portfolio
                    SET shares = ?, avg_price = ?, market_value = ?,
                        Total_Profit_Loss = ?, last_updated = ?, holding_type=?
                    WHERE ticker = ?
                    """,
                    (shares, avg_price, market_value,total_profit_loss, timestamp, holding_type, ticker),
                )
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
                            shares,
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

            current_shares = _to_float(existing["shares"])
            new_shares = current_shares - float(shares)

            if new_shares <= 0:
                conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
            else:
                avg_price_existing = _to_float(existing["avg_price"])
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
                WHERE ticker = ?
                                """,
                        (
                            new_shares,
                            market_value,
                            total_profit_loss,
                            timestamp,
                            ticker,
                        ),
                                        )


dash.register_page(__name__, path="/")
layout = html.Div([
    html.H1(" Joe Zoghzoghi Portfolio Dashboard", style={"textAlign": "center", "marginBottom": "20px", "color": "#EA84FC"}),
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
        n_intervals=5,
    )
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
    print("\n=== CALLBACK TRIGGERED ===")
    print("Add:", add_clicks, "Remove:", remove_clicks)
    print("Triggered:", ctx.triggered)

   
    
    button_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else "inital load"
    print("Button clicked:", button_id)

    if button_id == "add-btn" and ticker and shares is not None and avg_price is not None and holding_type is not None:
        print("adding ticker...")
        modify_portfolio("add", ticker, shares, avg_price,holding_type)
        
    elif button_id == "remove-btn" and ticker:
        print("remove ticker...")
        modify_portfolio("remove", ticker, shares)
    elif button_id == "interval-component":
        update_prices()

    df = load_data()
    df["market_value_num"] = pd.to_numeric(df["market_value"], errors="coerce").fillna(0)
    df["current_price"] = pd.to_numeric(df["current_price"], errors="coerce").fillna(0)
    df["Total_Profit_Loss_num"] = pd.to_numeric(df["Total_Profit_Loss"], errors="coerce").fillna(0)
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
    return table_data, chart_fig,holding_fig