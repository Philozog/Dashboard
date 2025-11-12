import sqlite3
import pandas as pd

# Connect to your portfolio databasep
conn = sqlite3.connect("portfolio.db")

# Load your current table
df = pd.read_sql("SELECT * FROM portfolio", conn)

# ✅ Remove duplicates — keep the first occurrence of each ticker
df = df.drop_duplicates(subset=["ticker"], keep="first")

# Save the cleaned data back to the database
df.to_sql("portfolio_temporary", conn, if_exists="replace", index=False)
conn.execute("DROP TABLE portfolio")
conn.execute("ALTER TABLE portfolio_temporary RENAME TO portfolio")
conn.close()
print("✅ Duplicates removed successfully.")
