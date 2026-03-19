# resetear_bd.py
import sqlite3
DB_PATH = "data/backtest.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("DELETE FROM picks")
conn.execute("DELETE FROM sqlite_sequence WHERE name='picks'")
conn.commit()
conn.close()
print("✅ Base de datos reseteada. Lista para datos reales.")