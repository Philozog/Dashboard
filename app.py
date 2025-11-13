from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

import pandas as pd
from sqlalchemy import create_engine
from updater import update_prices 
import os
import sqlite3
engine = create_engine("sqlite:///portfolio.db")

if not os.path.exists("portfolio.db"):
    import data_base  # Initialize the database if it doesn't exist


def load_data():
    with sqlite3.connect("portfolio.db") as conn:
        try:
            df = pd.read_sql("SELECT * FROM portfolio", conn)
        except Exception as e:
            print("⚠️ Table missing, creating schema automatically...")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT,
                    shares REAL,
                    avg_price REAL,
                    current_price REAL,
                    market_value REAL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            df = pd.DataFrame(columns=[
                "id", "ticker", "shares", "avg_price",
                "current_price", "market_value", "last_updated"
            ])
        return df

def modify_portfolio(action, ticker, shares=None, avg_price=None):
    conn = sqlite3.connect("portfolio.db")
    df = pd.read_sql("SELECT * FROM portfolio", conn)
    

    ticker = ticker.upper()
    
    if ticker in df["ticker"].values: # Make sure Ticker exists

        if action == "add":
                # Update the existing ticker
                df.loc[df["ticker"] == ticker, "shares"] = shares
                df.loc[df["ticker"] == ticker, "avg_price"] = avg_price
            

        elif action == "remove":
            if shares is not None:
                df.loc[df["ticker"] == ticker, "shares"] -= shares
            if df.loc[df["ticker"] == ticker, "shares"].values[0] <= 0:
                df = df[df["ticker"] != ticker]
    
    else: #Ticket not in portfolio        
        if action =="add":
             new_row = pd.DataFrame([{
                    "ticker": ticker,
                    "shares": shares,
                    "avg_price": avg_price,
                    "current_price": 0,
                    "market_value": shares * avg_price ,
                    "last_updated": pd.Timestamp.now()
                }])
             df = pd.concat([df, new_row], ignore_index=True)
        else:
            raise ValueError("Ticker not found in portfolio.")

    if "last_updated" in df.columns:
            df["last_updated"] = df["last_updated"].astype(str)

    df.to_sql("portfolio", conn, if_exists="replace", index=False)
    print("portfolio updated", df)
    conn.commit()
    conn.close()


app = Dash(__name__)

app.layout = html.Div([
    html.H1("Joe Z Portfolio Dashboard"),

    # === INPUT SECTION ===
    html.Div([
        dcc.Input(id="ticker-input", type="text", placeholder="Ticker (e.g. AAPL)"),
        dcc.Input(id="shares-input", type="number", placeholder="Shares", min=1),
        dcc.Input(id="avgprice-input", type="number", placeholder="Average Price", min=0),
        html.Button("Add Ticker", id="add-btn", n_clicks=0, style={"marginRight": "10px"}),
        html.Button("Remove Ticker", id="remove-btn", n_clicks=0)
    ], style={"marginBottom": "20px"}),

    # === DATA TABLE ===
    dash_table.DataTable(
        id="portfolio-table",
        columns=[{"name": i, "id": i,"type":"text"} for i in load_data().columns],
        data=load_data().to_dict("records")
    ),

    # === CHART ===
    dcc.Graph(id="value-chart"),

    # === AUTO REFRESH ===
    dcc.Interval(
        id="interval-component",
        interval=60 * 1000,  # 1 minute
        n_intervals=1
    )
])



    

@app.callback(
    Output("portfolio-table", "data"),

    [Input("add-btn", "n_clicks"),
     Input("remove-btn", "n_clicks"),
     Input("interval-component", "n_intervals")],

    [State("ticker-input", "value"),
     State("shares-input", "value"),
     State("avgprice-input", "value")]
)

def modify_data(add_clicks, remove_clicks, n_intervals, ticker, shares, avg_price):
    from dash import callback_context
    ctx = callback_context

    print("\n=== CALLBACK TRIGGERED ===")
    print("Add:", add_clicks, "Remove:", remove_clicks)
    print("Triggered:", ctx.triggered)

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    print("Button clicked:", button_id)

    if button_id == "add-btn" and ticker and shares is not None and avg_price is not None:
        print("adding ticker...")
        modify_portfolio("add", ticker, shares, avg_price)
    
    elif button_id == "remove-btn" and ticker:
        print("Remove Ticker...")
        modify_portfolio("remove", ticker,shares,avg_price)

    # update prices every interval
    elif button_id == "interval-component":
        update_prices()
       
    #Load and Format Data
    df = load_data()
    df["market_value"] = df["market_value"].apply(lambda x:f"{x:,.0f}")
    return df.to_dict("records")

if __name__ == "__main__":
    app.run(debug=True,reloader=False)
