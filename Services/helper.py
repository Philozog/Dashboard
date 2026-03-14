import sqlite3
import pandas as pd


DB_PATH = "portfolio.db"


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
    return df
