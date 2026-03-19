import sqlite3
import pandas as pd
from pathlib import Path
from contextlib import contextmanager
from config import DB_PATH, BANKROLL_INICIAL_COP, STAKE_PORCENTAJE
import logging
import os
import hashlib
import re
import unicodedata

logger = logging.getLogger(__name__)


def _norm_text(texto):
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return " ".join(texto.split())

@contextmanager
def get_conn():
    """
    Context manager para manejo seguro de conexiones a la base de datos.
    Garantiza que las conexiones se cierren correctamente.
    """
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20.0)  # Timeout para evitar bloqueos
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en transacción de BD: {e}")
        raise
    finally:
        conn.close()

def init_db():
    """Inicializa la base de datos con índices optimizados."""
    with get_conn() as conn:
        # Tabla principal de picks
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
                resultado TEXT DEFAULT 'pendiente' 
                    CHECK(resultado IN ('ganada','perdida','media','pendiente')),
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
            
            -- ÍNDICES para optimizar consultas frecuentes
            CREATE INDEX IF NOT EXISTS idx_picks_fecha ON picks(fecha);
            CREATE INDEX IF NOT EXISTS idx_picks_ia ON picks(ia);
            CREATE INDEX IF NOT EXISTS idx_picks_resultado ON picks(resultado);
            CREATE INDEX IF NOT EXISTS idx_picks_tipo ON picks(tipo_pick);
            CREATE INDEX IF NOT EXISTS idx_picks_partido ON picks(partido);
            CREATE INDEX IF NOT EXISTS idx_picks_batch ON picks(import_batch);
            CREATE INDEX IF NOT EXISTS idx_picks_compuesto ON picks(fecha, ia, resultado);
            
            -- Tabla de configuración
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Tabla de caché de cuotas (nueva - para Fase 4)
            CREATE TABLE IF NOT EXISTS cuotas_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                liga_key TEXT NOT NULL,
                partido TEXT NOT NULL,
                bookmaker TEXT NOT NULL,
                cuota_local REAL,
                cuota_empate REAL,
                cuota_visitante REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ttl_minutes INTEGER DEFAULT 5,
                UNIQUE(liga_key, partido, bookmaker)
            );
            
            CREATE INDEX IF NOT EXISTS idx_cache_lookup ON cuotas_cache(liga_key, partido, bookmaker);
            CREATE INDEX IF NOT EXISTS idx_cache_timestamp ON cuotas_cache(timestamp);

            CREATE TABLE IF NOT EXISTS team_assets (
                team_key TEXT PRIMARY KEY,
                team_name TEXT NOT NULL,
                logo_url TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_team_assets_name ON team_assets(team_name);

            CREATE TABLE IF NOT EXISTS prepared_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partido TEXT NOT NULL,
                fecha TEXT,
                liga TEXT,
                cobertura REAL DEFAULT 0,
                ficha_texto TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_prepared_matches_partido ON prepared_matches(partido);
            CREATE INDEX IF NOT EXISTS idx_prepared_matches_fecha ON prepared_matches(fecha);

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
                last_login DATETIME
            );

            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
        """)
        
        # Insertar configuración inicial si no existe
        conn.execute("""
            INSERT OR IGNORE INTO config (key, value) 
            VALUES ('bankroll_inicial', ?)
        """, (str(BANKROLL_INICIAL_COP),))
        
        conn.execute("""
            INSERT OR IGNORE INTO config (key, value) 
            VALUES ('stake_porcentaje', ?)
        """, (str(STAKE_PORCENTAJE),))
        
        conn.execute("""
            INSERT OR IGNORE INTO config (key, value) 
            VALUES ('db_version', '1.1')
        """)
        
        logger.info("✅ Base de datos inicializada correctamente con índices optimizados")

        user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "must_change_password" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

def get_bankroll_inicial():
    """Obtiene el bankroll inicial de forma segura."""
    try:
        with get_conn() as conn:
            val = conn.execute(
                "SELECT value FROM config WHERE key='bankroll_inicial'"
            ).fetchone()
            return float(val[0]) if val else BANKROLL_INICIAL_COP
    except Exception as e:
        logger.error(f"Error obteniendo bankroll: {e}")
        return BANKROLL_INICIAL_COP

def get_stake_porcentaje():
    """Obtiene el porcentaje de stake de forma segura."""
    try:
        with get_conn() as conn:
            val = conn.execute(
                "SELECT value FROM config WHERE key='stake_porcentaje'"
            ).fetchone()
            return float(val[0]) if val else STAKE_PORCENTAJE
    except Exception as e:
        logger.error(f"Error obteniendo stake: {e}")
        return STAKE_PORCENTAJE

def update_config(key, value):
    try:
        with get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
    except Exception as e:
        logger.error(f"Error actualizando config {key}: {e}")


def get_config_value(key, default=None):
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?",
                (key,),
            ).fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.error(f"Error obteniendo config {key}: {e}")
        return default


def _hash_password(password: str, salt: str = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    return _hash_password(password, salt) == stored_hash


def create_user(username, display_name, password, email=None, role="user", must_change_password=False):
    if not username or not display_name or not password:
        raise ValueError("username, display_name y password son obligatorios")
    username = str(username).strip().lower()
    display_name = str(display_name).strip()
    email = str(email).strip().lower() if email else None
    password_hash = _hash_password(password)
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO users (username, display_name, email, password_hash, role, active, must_change_password)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (username, display_name, email, password_hash, role, 1 if must_change_password else 0),
            )
        return True, "Usuario creado correctamente."
    except sqlite3.IntegrityError as e:
        texto = str(e).lower()
        if "username" in texto:
            return False, "Ese nombre de usuario ya existe."
        if "email" in texto:
            return False, "Ese email ya existe."
        return False, "No se pudo crear el usuario por restriccion de datos."
    except Exception as e:
        logger.error(f"Error creando usuario {username}: {e}")
        return False, f"No se pudo crear el usuario: {e}"


def authenticate_user(username, password):
    username = str(username or "").strip().lower()
    if not username or not password:
        return None
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, email, password_hash, role, active, must_change_password
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
            if not row:
                return None
            if int(row[6]) != 1:
                return None
            if not _verify_password(password, row[4]):
                return None
            conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                (row[0],),
            )
            return {
                "id": row[0],
                "username": row[1],
                "display_name": row[2],
                "email": row[3],
                "role": row[5],
                "active": bool(row[6]),
                "must_change_password": bool(row[7]),
            }
    except Exception as e:
        logger.error(f"Error autenticando usuario {username}: {e}")
        return None


def get_all_users():
    try:
        with get_conn() as conn:
            return pd.read_sql(
                """
                SELECT id, username, display_name, email, role, active, created_at, last_login, must_change_password
                FROM users
                ORDER BY created_at DESC, id DESC
                """,
                conn,
            )
    except Exception as e:
        logger.error(f"Error obteniendo usuarios: {e}")
        return pd.DataFrame()


def update_user_status(user_id, active):
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET active = ? WHERE id = ?",
                (1 if active else 0, int(user_id)),
            )
        return True, "Estado de usuario actualizado."
    except Exception as e:
        logger.error(f"Error actualizando estado de usuario {user_id}: {e}")
        return False, f"No se pudo actualizar el usuario: {e}"


def update_user_profile(user_id, display_name, email=None):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, email = ?
                WHERE id = ?
                """,
                (str(display_name).strip(), str(email).strip().lower() if email else None, int(user_id)),
            )
        return True, "Perfil actualizado correctamente."
    except sqlite3.IntegrityError as e:
        texto = str(e).lower()
        if "email" in texto:
            return False, "Ese email ya esta en uso."
        return False, "No se pudo actualizar el perfil."
    except Exception as e:
        logger.error(f"Error actualizando perfil de usuario {user_id}: {e}")
        return False, f"No se pudo actualizar el perfil: {e}"


def update_user_password(user_id, current_password, new_password):
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
            if not row:
                return False, "Usuario no encontrado."
            if not _verify_password(current_password, row[0]):
                return False, "La clave actual no coincide."
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (_hash_password(new_password), int(user_id)),
            )
        return True, "Clave actualizada correctamente."
    except Exception as e:
        logger.error(f"Error actualizando clave de usuario {user_id}: {e}")
        return False, f"No se pudo actualizar la clave: {e}"


def set_must_change_password(user_id, value=True):
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET must_change_password = ? WHERE id = ?",
                (1 if value else 0, int(user_id)),
            )
        return True, "Estado de cambio de clave actualizado."
    except Exception as e:
        logger.error(f"Error actualizando must_change_password para usuario {user_id}: {e}")
        return False, f"No se pudo actualizar el estado de la clave: {e}"


def get_cached_team_logo(team_name):
    clave = _norm_text(team_name)
    if not clave:
        return ""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT logo_url FROM team_assets WHERE team_key = ?",
                (clave,),
            ).fetchone()
            return str(row[0] or "").strip() if row else ""
    except Exception as e:
        logger.error(f"Error obteniendo logo cacheado para {team_name}: {e}")
        return ""


def save_cached_team_logo(team_name, logo_url):
    clave = _norm_text(team_name)
    nombre = str(team_name or "").strip()
    logo = str(logo_url or "").strip()
    if not clave or not nombre:
        return False
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO team_assets (team_key, team_name, logo_url, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(team_key) DO UPDATE SET
                    team_name = excluded.team_name,
                    logo_url = excluded.logo_url,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (clave, nombre, logo),
            )
        return True
    except Exception as e:
        logger.error(f"Error guardando logo cacheado para {team_name}: {e}")
        return False


def save_prepared_match(partido, fecha, liga, cobertura, ficha_texto):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO prepared_matches (partido, fecha, liga, cobertura, ficha_texto)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(partido or "").strip(),
                    str(fecha or "").strip(),
                    str(liga or "").strip(),
                    float(cobertura or 0),
                    str(ficha_texto or "").strip(),
                ),
            )
        return True, "Ficha preparada guardada."
    except Exception as e:
        logger.error(f"Error guardando ficha preparada: {e}")
        return False, f"No se pudo guardar la ficha preparada: {e}"


def get_prepared_matches(limit=20):
    try:
        with get_conn() as conn:
            return pd.read_sql(
                f"""
                SELECT id, partido, fecha, liga, cobertura, ficha_texto, created_at
                FROM prepared_matches
                ORDER BY id DESC
                LIMIT {int(limit)}
                """,
                conn,
            )
    except Exception as e:
        logger.error(f"Error obteniendo fichas preparadas: {e}")
        return pd.DataFrame()

def save_picks(df, batch_id):
    """
    Guarda picks de forma segura con manejo de transacciones.
    Ahora soporta picks principales y alternativas.
    """
    if df.empty:
        logger.warning("DataFrame vacío, no se guardaron picks")
        return {"insertados": 0, "duplicados": 0}
    
    try:
        with get_conn() as conn:
            # Asegurar que existan todas las columnas necesarias
            columnas_requeridas = ['competicion', 'tipo_handicap', 'linea', 'confianza', 'analisis_breve', 'tipo_pick']
            for col in columnas_requeridas:
                if col not in df.columns:
                    df[col] = None
            
            # Asegurar que tipo_pick tenga valor por defecto
            if 'tipo_pick' not in df.columns or df['tipo_pick'].isna().all():
                df['tipo_pick'] = 'principal'
            
            df['import_batch'] = batch_id
            
            # Calcular stake basado en bankroll actual
            bankroll = get_bankroll_inicial()
            stake_porc = get_stake_porcentaje()
            df['stake'] = round(bankroll * stake_porc / 100, 2)
            df['resultado'] = 'pendiente'
            df['ganancia'] = 0.0
            df['cuota_real'] = df['cuota'].fillna(0)
            
            picks_insertados = 0
            picks_duplicados = 0
            
            for _, row in df.iterrows():
                try:
                    conn.execute("""
                        INSERT INTO picks
                        (fecha, partido, ia, mercado, seleccion, cuota, cuota_real, confianza,
                         stake, resultado, ganancia, analisis_breve, competicion, tipo_handicap,
                         linea, import_batch, tipo_pick)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row['fecha'], row['partido'], row['ia'], row['mercado'], 
                        row['seleccion'], float(row['cuota']), float(row['cuota_real']), 
                        row.get('confianza'),
                        float(row['stake']), row['resultado'], float(row['ganancia']), 
                        row.get('analisis_breve'),
                        row.get('competicion'), row.get('tipo_handicap'), 
                        row.get('linea'),
                        row['import_batch'], row['tipo_pick']
                    ))
                    picks_insertados += 1
                except sqlite3.IntegrityError:
                    # Pick duplicado (misma fecha, partido, ia, mercado, seleccion, tipo)
                    picks_duplicados += 1
                    continue
            
            logger.info(f"✅ {picks_insertados} picks insertados, {picks_duplicados} duplicados ignorados")
            return {"insertados": picks_insertados, "duplicados": picks_duplicados}

    except Exception as e:
        logger.error(f"❌ Error guardando picks: {e}")
        raise

def get_all_picks(incluir_alternativas=False):
    """
    Obtiene todos los picks de forma optimizada.
    Usa índices para mejor rendimiento.
    """
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(picks)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Construir query usando índices
            if 'tipo_pick' in columns:
                if incluir_alternativas:
                    query = """
                        SELECT * FROM picks 
                        ORDER BY fecha DESC, id DESC
                    """
                else:
                    query = """
                        SELECT * FROM picks 
                        WHERE tipo_pick = 'principal' 
                        ORDER BY fecha DESC, id DESC
                    """
            else:
                query = "SELECT * FROM picks ORDER BY fecha DESC, id DESC"
            
            df = pd.read_sql(query, conn)
            
            # Asegurar compatibilidad hacia atrás
            if 'tipo_pick' not in df.columns:
                df['tipo_pick'] = 'principal'
            
            return df
            
    except Exception as e:
        logger.error(f"Error obteniendo picks: {e}")
        return pd.DataFrame()  # Retornar DataFrame vacío en caso de error

def update_resultado_con_cuota(pick_id, resultado, cuota_real):
    """
    Actualiza el resultado de un pick calculando la ganancia automáticamente.
    Soporta: 'ganada', 'perdida', 'media' (para handicaps asiáticos)
    """
    if not pick_id or not resultado:
        raise ValueError("pick_id y resultado son requeridos")
    
    try:
        with get_conn() as conn:
            # Obtener stake del pick
            stake_row = conn.execute(
                "SELECT stake FROM picks WHERE id = ?", 
                (pick_id,)
            ).fetchone()
            
            if not stake_row:
                raise ValueError(f"No existe pick con id {pick_id}")
            
            stake = float(stake_row[0])
            
            # Calcular ganancia según resultado
            if resultado == 'ganada':
                ganancia = stake * (float(cuota_real) - 1)
            elif resultado == 'perdida':
                ganancia = -stake
            elif resultado == 'media':
                # Para handicaps asiáticos .25/.75
                ganancia = (stake / 2.0) * (float(cuota_real) - 1)
            else:
                raise ValueError(f"Resultado no válido: {resultado}")
            
            # Actualizar pick
            conn.execute("""
                UPDATE picks 
                SET resultado = ?, ganancia = ?, cuota_real = ?
                WHERE id = ?
            """, (resultado, round(ganancia, 2), float(cuota_real), pick_id))
            
            logger.info(f"✅ Pick {pick_id} actualizado: {resultado}, ganancia: {ganancia:.2f}")
            
    except Exception as e:
        logger.error(f"Error actualizando pick {pick_id}: {e}")
        raise

def delete_all_picks():
    """Elimina todos los picks de forma segura (con confirmación previa recomendada)."""
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM picks")
            conn.execute("DELETE FROM sqlite_sequence WHERE name='picks'")
            logger.warning("🗑️ Todos los picks han sido eliminados")
    except Exception as e:
        logger.error(f"Error eliminando picks: {e}")
        raise

def get_stats_resumen():
    """
    Obtiene estadísticas rápidas de la base de datos.
    Útil para el dashboard.
    """
    try:
        with get_conn() as conn:
            stats = {}
            
            # Total de picks
            cursor = conn.execute("SELECT COUNT(*) FROM picks")
            stats['total_picks'] = cursor.fetchone()[0]
            
            # Picks por estado
            cursor = conn.execute("""
                SELECT resultado, COUNT(*) 
                FROM picks 
                GROUP BY resultado
            """)
            stats['por_estado'] = dict(cursor.fetchall())
            
            # Picks por IA
            cursor = conn.execute("""
                SELECT ia, COUNT(*) 
                FROM picks 
                GROUP BY ia 
                ORDER BY COUNT(*) DESC
            """)
            stats['por_ia'] = dict(cursor.fetchall())
            
            # Rango de fechas
            cursor = conn.execute("""
                SELECT MIN(fecha), MAX(fecha) 
                FROM picks
            """)
            stats['rango_fechas'] = cursor.fetchone()
            
            return stats
            
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        return {}
