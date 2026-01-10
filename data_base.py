
# DATABASE CREATION SCRIPT

import sqlite3
conn = sqlite3.connect('portfolio.db')
with open('schema.sql', 'r') as f:
    conn.executescript(f.read())
conn.close()



