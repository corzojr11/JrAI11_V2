import sqlite3
import pandas as pd
from pathlib import Path
from config import DB_PATH, BANKROLL_INICIAL, STAKE_PORCENTAJE

def get_conn():
    Path("data").mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        partido TEXT NOT NULL,
        ia TEXT NOT NULL,
        mercado TEXT NOT NULL,
        seleccion TEXT NOT NULL,
        cuota REAL NOT NULL,
        confianza REAL,
        stake REAL NOT NULL DEFAULT 0,
        resultado TEXT DEFAULT 'pendiente' CHECK(resultado IN ('ganada','perdida','media','pendiente')),
        ganancia REAL DEFAULT 0.0,
        analisis_breve TEXT,
        competicion TEXT,
        tipo_handicap TEXT,
        linea REAL,
        import_batch TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(fecha, partido, ia, mercado, seleccion)
    );

    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    
    conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bankroll_inicial', ?)", 
                (str(BANKROLL_INICIAL),))
    conn.commit()
    conn.close()

def get_bankroll_inicial():
    conn = get_conn()
    val = conn.execute("SELECT value FROM config WHERE key='bankroll_inicial'").fetchone()
    conn.close()
    return float(val[0]) if val else BANKROLL_INICIAL

def save_picks(df, batch_id):
    conn = get_conn()
    df['import_batch'] = batch_id
    df['stake'] = round(get_bankroll_inicial() * STAKE_PORCENTAJE / 100, 2)
    df['resultado'] = 'pendiente'
    df['ganancia'] = 0.0
    df.to_sql('picks', conn, if_exists='append', index=False, method='multi')
    conn.close()

def get_all_picks():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM picks ORDER BY fecha, id", conn)
    conn.close()
    return df

def update_resultado(pick_id, resultado):
    conn = get_conn()
    if resultado == 'ganada':
        ganancia = "cuota * stake - stake"
    elif resultado == 'perdida':
        ganancia = "-stake"
    elif resultado == 'media':
        ganancia = "(stake / 2.0) * (cuota - 1)"
    else:
        ganancia = "0"

    conn.execute(f"""
        UPDATE picks 
        SET resultado = ?, ganancia = {ganancia}
        WHERE id = ?
    """, (resultado, pick_id))
    conn.commit()
    conn.close()

def delete_all_picks():
    conn = get_conn()
    conn.execute("DELETE FROM picks")
    conn.commit()
    conn.close()