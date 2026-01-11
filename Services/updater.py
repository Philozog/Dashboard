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
        time_since_update=(datetime.now() - last_updated_time).total_seconds()
        if row["current_price"] != 0 and time_since_update < 900:
            continue
    
        ticker = row["ticker"]
        try:
            data = yf.Ticker(ticker).history(period="1d")
            if not data.empty:
                latest_price = data["Close"].iloc[-1]
                df.loc[i, "current_price"] = round(latest_price,2)
                df.loc[i, "last_updated"] = datetime.now()
                df.loc[i,"market_value"]= df.loc[i,"shares"] * df.loc[i,"current_price"]
                df.loc[i,"Total_Profit_Loss"]=(df.loc[i,"current_price"] - df.loc[i,"avg_price"]) * df.loc[i,"shares"]
                df.loc[i,"Total_Market_Value"]="---"
                print(f"✅ Updated {ticker}: {latest_price}")
        except Exception as e:
            print(f"⚠️ Could not update {ticker}: {e}")

    

if __name__ == "__main__":
    print("🔄 Fetching new prices from Yahoo Finance...")
    update_prices()
    print("✅ All prices updated successfully!")