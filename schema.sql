#SQL SKELETON FOR PORTFOLIO DATABASE

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE,
    shares REAL,
    avg_price REAL,
    current_price REAL,
    market_value REAL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Total_Profit_Loss REAL
);


