-- Canonical schema. Upgrades are managed by Services.database.
CREATE TABLE IF NOT EXISTS portfolio (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL UNIQUE,
 shares REAL NOT NULL CHECK(shares >= 0), avg_price REAL NOT NULL CHECK(avg_price >= 0),
 current_price REAL, market_value REAL, last_updated TEXT, quote_updated_at TEXT, quote_checked_at TEXT,
 Total_Profit_Loss REAL, holding_type TEXT NOT NULL DEFAULT 'Unassigned'
);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('opening','buy','sell','deposit','withdrawal','dividend','fee')),
 ticker TEXT, shares REAL NOT NULL DEFAULT 0, price REAL NOT NULL DEFAULT 0,
 amount REAL NOT NULL DEFAULT 0, fees REAL NOT NULL DEFAULT 0,
 realized_pnl REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS valuations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
 nav REAL NOT NULL, external_flow REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
