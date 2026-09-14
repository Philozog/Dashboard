
# DATABASE CREATION SCRIPT

import sqlite3

from Services.database import BASE_DIR, DB_PATH


conn = sqlite3.connect(DB_PATH)
with open(BASE_DIR / 'schema.sql', 'r') as f:
    conn.executescript(f.read())
conn.close()



