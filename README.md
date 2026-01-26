# 📊 Portfolio Dashboard & Price Updater

A Python-based personal portfolio management system that tracks equity holdings, updates live prices from Yahoo Finance, and visualizes portfolio allocation through an interactive dashboard.

This project is designed to be **simple, reliable, and production-safe**, avoiding common pitfalls such as duplicate rows, table rewrites, or misleading “fake live” prices.

---

## 🚀 Features

- ✅ One row per holding (ticker-based portfolio)
- ✅ Live price updates via Yahoo Finance (`yfinance`)
- ✅ Safe, row-level SQL updates (no table replacement)
- ✅ Automatic market value & P&L calculation
- ✅ Stale-price protection (15-minute refresh logic)
- ✅ Interactive dashboard for portfolio allocation
- ✅ SQLite backend (lightweight & local)

---

## 🧠 Architecture Overview

**Core idea:**  
> *Positions are rows. Prices are attributes. Prices get updated — rows are never recreated.*

### Components
- **SQLite database** (`portfolio.db`)  
  Stores holdings and computed fields
- **Price updater service** (`Services/updater.py`)  
  Fetches prices and updates existing rows
- **Dashboard app**  
  Displays holdings, totals, and allocation charts

---

## 🗄️ Database Schema

```sql
CREATE TABLE IF NOT EXISTS portfolio (
    ticker TEXT PRIMARY KEY,
    shares REAL NOT NULL,
    avg_price REAL NOT NULL,
    current_price REAL,
    market_value REAL,
    last_updated TIMESTAMP,
    Total_Profit_Loss REAL
);
