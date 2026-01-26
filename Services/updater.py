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

                # Decide if update needed
                if row["current_price"] and row["last_updated"]:
                    age = (datetime.now() - pd.to_datetime(row["last_updated"])).total_seconds()
                    if age < 900:
                        continue  # price is fresh

                # Fetch price
                data = yf.Ticker(row["ticker"]).history(period="1d")
                if data.empty:
                    continue

                price = round(data["Close"].iloc[-1], 2)

            # Update ONLY this row
                conn.execute(
        text("""
        UPDATE portfolio
        SET
            current_price = :price,
            market_value = :market_value,
            Total_Profit_Loss = :pnl,
            last_updated = :last_updated
        WHERE ticker = :ticker
    """),
    {
        "price": price,
        "market_value": price * row["shares"],
        "pnl": (price - row["avg_price"]) * row["shares"],
        "last_updated": datetime.now(),
        "ticker": row["ticker"],
    }
)
       

 

if __name__ == "__main__":
    print("Fetching new prices from Yahoo Finance...")
    update_prices()
    print("✅ All prices updated successfully!")