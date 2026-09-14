import sqlite3
import pandas as pd

from Services.database import DB_PATH


EXPECTED_COLUMNS = [
    "id",
    "ticker",
    "shares",
    "avg_price",
    "current_price",
    "market_value",
    "last_updated",
    "Total_Profit_Loss",
    "holding_type",
]

def _collapse_duplicate_tickers(df):
    if df.empty or "ticker" not in df.columns:
        return df

    df = df.copy()
    df["ticker"] = df["ticker"].fillna("").astype(str).str.strip().str.upper()
    holdings = df[df["ticker"] != ""].copy()
    blanks = df[df["ticker"] == ""].copy()
    if holdings.empty:
        return df

    for column in ["shares", "avg_price", "current_price", "market_value", "Total_Profit_Loss"]:
        holdings[column] = pd.to_numeric(holdings[column], errors="coerce").fillna(0.0)

    rows = []
    for ticker, group in holdings.groupby("ticker", sort=False):
        shares = group["shares"].sum()
        avg_price = 0.0
        if shares > 0:
            avg_price = (group["shares"] * group["avg_price"]).sum() / shares

        current_price_values = group.loc[group["current_price"] > 0, "current_price"]
        current_price = current_price_values.iloc[-1] if not current_price_values.empty else 0.0
        price_basis = current_price if current_price else avg_price
        market_value = price_basis * shares
        total_profit_loss = (current_price - avg_price) * shares if current_price else 0.0

        holding_type_values = group["holding_type"].dropna().astype(str)
        holding_type_values = holding_type_values[holding_type_values.str.strip() != ""]
        holding_type = holding_type_values.iloc[-1] if not holding_type_values.empty else None

        last_updated_values = group["last_updated"].dropna().astype(str)
        last_updated = last_updated_values.max() if not last_updated_values.empty else None

        rows.append({
            "id": group["id"].iloc[0],
            "ticker": ticker,
            "shares": shares,
            "avg_price": avg_price,
            "current_price": current_price,
            "market_value": market_value,
            "last_updated": last_updated,
            "Total_Profit_Loss": total_profit_loss,
            "holding_type": holding_type,
        })

    collapsed = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    if not blanks.empty:
        collapsed = pd.concat([collapsed, blanks[EXPECTED_COLUMNS]], ignore_index=True)
    return collapsed

def load_data():
    with sqlite3.connect(DB_PATH) as conn:
        try:
            df = pd.read_sql("SELECT * FROM portfolio", conn)
        except Exception:
            print("Table missing, creating schema automatically...")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT,
                    shares REAL,
                    avg_price REAL,
                    current_price REAL,
                    market_value REAL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    Total_Profit_Loss REAL
                )
                """
            )
            conn.commit()
            df = pd.DataFrame(columns=EXPECTED_COLUMNS)

        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(portfolio)").fetchall()
        }
        if "holding_type" not in existing_columns:
            conn.execute("ALTER TABLE portfolio ADD COLUMN holding_type TEXT")
            conn.commit()
            if "holding_type" not in df.columns:
                df["holding_type"] = None

    for column in EXPECTED_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df = df.drop(columns=["Total_Market_Value"], errors="ignore")
    df = df[EXPECTED_COLUMNS]
    return _collapse_duplicate_tickers(df)
