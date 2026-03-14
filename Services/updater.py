import yfinance as yf
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime


# DATA from YAHOO FINANCE
# Connect to your existing database
# KEEP Dashboard Current and LIVE
engine = create_engine("sqlite:///portfolio.db")

def update_prices():
    df = pd.read_sql("SELECT * FROM portfolio", engine)

    with engine.begin() as conn:
        for _, row in df.iterrows():
            ticker = str(row.get("ticker", "")).strip().upper()
            if not ticker:
                continue

            if pd.notna(row["current_price"]) and pd.notna(row["last_updated"]):
                age = (datetime.now() - pd.to_datetime(row["last_updated"])).total_seconds()
                if age < 900:
                    continue

            try:
                data = yf.Ticker(ticker).history(period="1d")
            except Exception:
                continue
            if data.empty:
                continue

            price = round(data["Close"].iloc[-1], 2)

            conn.execute(
                text(
                    """
                    UPDATE portfolio
                    SET
                        current_price = :price,
                        market_value = :market_value,
                        Total_Profit_Loss = :pnl,
                        last_updated = :last_updated
                    WHERE ticker = :ticker
                    """
                ),
                {
                    "price": price,
                    "market_value": price * row["shares"],
                    "pnl": (price - row["avg_price"]) * row["shares"],
                    "last_updated": datetime.now(),
                    "ticker": ticker,
                },
            )
       

 

if __name__ == "__main__":
    print("Fetching new prices from Yahoo Finance...")
    update_prices()
    print("✅ All prices updated successfully!")
