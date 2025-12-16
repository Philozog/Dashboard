#SQL SKELETON FOR PORTFOLIO DATABASE

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE,
    shares REAL,
    avg_price REAL,
    current_price REAL,
    Market_Value REAL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Total_Market_Value REAL,
    Total_Profit_Loss REAL
);
