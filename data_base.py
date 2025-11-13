
# DATABASE CREATION SCRIPT

import sqlite3
conn = sqlite3.connect('portfolio.db')
with open('schema.sql', 'r') as f:
    conn.executescript(f.read())
conn.close()



'''''''''''
import sqlite3

conn = sqlite3.connect("portfolio.db")
cur = conn.cursor()
cur.executemany("INSERT INTO portfolio (ticker, shares, avg_price, current_price,market_value) VALUES (?, ?, ?, ?,?)", [
    ("AMZN", 200,153, 185, 185*200),
    ("GOOG", 375, 103, 220,375*220)
])
conn.commit()
conn.close()

'''''''''''