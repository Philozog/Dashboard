import yfinance as yf
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime
# DATA from YAHOO FINANCE
# Connect to your existing database
# KEEP Dashboard Current and LIVE
engine = create_engine("sqlite:///portfolio.db")

def update_prices():
    df = pd.read_sql("SELECT * FROM portfolio", engine)

    # Loop through each ticker and get live price
    for i, row in df.iterrows():
        last_updated_time = pd.to_datetime(row["last_updated"])
        if (datetime.now() - last_updated_time).seconds < 900:
            continue  # Skip if updated within last 15 minutes
    
        ticker = row["ticker"]
        try:
            data = yf.Ticker(ticker).history(period="1d")
            if not data.empty:
                latest_price = data["Close"].iloc[-1]
                df.loc[i, "current_price"] = round(latest_price,2)
                df.loc[i, "last_updated"] = datetime.now()
                df.loc[i,"market_value"]= round(df.loc[i,"shares"] * df.loc[i,"current_price"],2)
                print(f"✅ Updated {ticker}: {latest_price}")
        except Exception as e:
            print(f"⚠️ Could not update {ticker}: {e}")

    # Overwrite portfolio table with new prices
    df.to_sql("portfolio", engine, if_exists="replace", index=False)

if __name__ == "__main__":
    print("🔄 Fetching new prices from Yahoo Finance...")
    update_prices()
    print("✅ All prices updated successfully!")