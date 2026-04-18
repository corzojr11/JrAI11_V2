"""
Fixtures pytest para tests aislados.
Debe cargarse antes que cualquier otro módulo que use database.
"""
import os
import sys
import pytest
import tempfile
import sqlite3

# Asegurar que config se cargue primero
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="function")
def temp_db(monkeypatch):
    """
    Crea una base de datos SQLite temporal para cada test.
    Reemplaza la DB_PATH en config ANTES de importar database.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    # Importar config y modificar DB_PATH antes de que database se importe
    import config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    
    # Forzar recarga de database con la nueva ruta
    if "database" in sys.modules:
        del sys.modules["database"]
    
    # Importar database con la nueva ruta
    import database
    database.DB_PATH = db_path
    
    # Crear esquema en la BD temporal
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            partido TEXT NOT NULL,
            ia TEXT NOT NULL,
            mercado TEXT NOT NULL,
            seleccion TEXT NOT NULL,
            cuota REAL NOT NULL CHECK(cuota >= 1.01 AND cuota <= 100.0),
            cuota_real REAL DEFAULT 0.0 CHECK(cuota_real >= 1.01 OR cuota_real = 0.0),
            confianza REAL CHECK(confianza >= 0 AND confianza <= 1),
            stake REAL NOT NULL DEFAULT 0 CHECK(stake > 0),
            resultado TEXT DEFAULT 'pendiente' CHECK(resultado IN ('ganada','perdida','media','pendiente')),
            ganancia REAL DEFAULT 0.0,
            analisis_breve TEXT,
            competicion TEXT,
            tipo_handicap TEXT,
            linea REAL,
            import_batch TEXT,
            tipo_pick TEXT DEFAULT 'principal' CHECK(tipo_pick IN ('principal', 'alternativa')),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fecha, partido, ia, mercado, seleccion, tipo_pick)
        );
        
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1)),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME,
            subscription_plan TEXT DEFAULT 'free',
            subscription_start DATETIME,
            subscription_end DATETIME
        );
        
        CREATE TABLE IF NOT EXISTS team_assets (
            team_key TEXT PRIMARY KEY,
            team_name TEXT NOT NULL,
            logo_url TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS prepared_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partido TEXT NOT NULL,
            fecha TEXT,
            liga TEXT,
            cobertura REAL DEFAULT 0,
            ficha_texto TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS cuotas_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            liga_key TEXT NOT NULL,
            partido TEXT NOT NULL,
            bookmaker TEXT NOT NULL,
            cuota_local REAL,
            cuota_empate REAL,
            cuota_visitante REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ttl_minutes INTEGER DEFAULT 5
        );
        
        INSERT INTO config (key, value) VALUES ('bankroll_inicial', '4000000');
        INSERT INTO config (key, value) VALUES ('stake_porcentaje', '2.0');
    """)
    conn.close()
    
    yield db_path
    
    # Limpieza
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture(scope="function")
def clean_user():
    """Generador de nombre de usuario único para tests."""
    import time
    return f"test_user_{int(time.time() * 1000000)}"


@pytest.fixture(scope="function")
def sample_user(temp_db, clean_user):
    """Crea un usuario de prueba en la base temporal."""
    from database import create_user
    ok, msg = create_user(
        username=clean_user,
        display_name="Test User",
        password="TestPassword123!",
        email=f"{clean_user}@test.com"
    )
    return {"username": clean_user, "ok": ok, "message": msg}
