import sqlite3
import pandas as pd


DB_PATH = "portfolio.db"

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
            df = pd.DataFrame(
                columns=[
                    "id",
                    "ticker",
                    "shares",
                    "avg_price",
                    "current_price",
                    "market_value",
                    "last_updated",
                    "Total_Market_Value",
                    "Total_Profit_Loss",
                ]
            )
    df=df.drop(columns=["Total_Market_Value"],errors='ignore')
    return df