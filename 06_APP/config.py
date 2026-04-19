# config.py
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# Silenciar logs de librerías de terceros ANTES de configurar el logger principal
for logger_name in ["fontTools", "fontTools.subset", "fontTools.ttLib", "fontTools.ttLib.tables", 
                   "fontTools.merge", "fpdf", "matplotlib", "PIL", "merge", "werkzeug"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
COOKIE_SECURE = APP_ENV == "production"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").strip().lower() or "lax"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

STAKE_PORCENTAJE = 2.0
BANKROLL_INICIAL_COP = 4_000_000
DB_PATH = str(BASE_DIR / "data" / "backtest.db")
CACHE_TTL_MINUTES = 5

BOOTSTRAP_TOKEN = os.getenv("BOOTSTRAP_TOKEN", "").strip()
if not BOOTSTRAP_TOKEN:
    raise ValueError(
        "BOOTSTRAP_TOKEN no está configurado. "
        "Crea un archivo .env con BOOTSTRAP_TOKEN=un_token_seguro para crear el primer administrador."
    )

if len(BOOTSTRAP_TOKEN) < 16:
    raise ValueError(
        "BOOTSTRAP_TOKEN es demasiado débil. "
        "Usa al menos 16 caracteres con mezcla de letras, números y símbolos."
    )

IAS_LIST = [
    "Kimi",
    "Qwen",
    "ChatGPT",
    "Grok",
    "Gemini",
    "DeepSeek",
    "Z.AI",
    "ERNIE",
    "Juez Final",
]


# ============================================
# TIPO DE CAMBIO USD/COP (Lazy loading)
# ============================================
_TIPO_CAMBIO_CACHE = {"valor": None, "timestamp": None}


def obtener_tipo_cambio_usd_cop():
    """Obtiene el tipo de cambio actual USD/COP de forma segura con cache."""
    from datetime import datetime, timedelta
    
    ahora = datetime.now()
    
    # Usar cache si existe y tiene menos de 1 hora
    if _TIPO_CAMBIO_CACHE["valor"] is not None and _TIPO_CAMBIO_CACHE["timestamp"]:
        if (ahora - _TIPO_CAMBIO_CACHE["timestamp"]) < timedelta(hours=1):
            return _TIPO_CAMBIO_CACHE["valor"]
    
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if "rates" in data and "COP" in data["rates"]:
                valor = data["rates"]["COP"]
                _TIPO_CAMBIO_CACHE["valor"] = valor
                _TIPO_CAMBIO_CACHE["timestamp"] = ahora
                return valor
    except Exception as e:
        logger.warning(f"Error obteniendo tipo de cambio: {e}")
    
    # Valor por defecto si falla
    return 4000


def get_usd_to_cop():
    """Función lazy para obtener tipo de cambio."""
    return obtener_tipo_cambio_usd_cop()


# Mantener compatibilidad hacia atrás
USD_TO_COP = 4000  # Valor por defecto hasta que se llame get_usd_to_cop()


# ============================================
# THE ODDS API
# ============================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
if not ODDS_API_KEY:
    logger.warning("ODDS_API_KEY no configurada. Las cuotas reales no estaran disponibles.")
    logger.info("Configura la variable de entorno ODDS_API_KEY en el archivo .env")


# ============================================
# API-FOOTBALL
# ============================================
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
if not API_FOOTBALL_KEY:
    logger.warning("API_FOOTBALL_KEY no configurada. El fallback no estara disponible.")
    logger.info("Configura la variable de entorno API_FOOTBALL_KEY en el archivo .env")


# ============================================
# TELEGRAM
# ============================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================
# ACCESO / ROLES
# ============================================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "123456").strip() or "123456"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if not JWT_SECRET_KEY:
    if APP_ENV == "production":
        raise ValueError("JWT_SECRET_KEY debe estar configurado en producción.")
    JWT_SECRET_KEY = "dev-only-change-me-please-keep-this-long"
    logger.warning("JWT_SECRET_KEY no configurada. Usando secreto de desarrollo temporal.")
elif len(JWT_SECRET_KEY) < 32 and APP_ENV == "production":
    raise ValueError("JWT_SECRET_KEY es demasiado débil para producción. Usa al menos 32 caracteres.")


# ============================================
# MONEDA VISUAL
# ============================================
MONEDA_PRINCIPAL = "COP"
MOSTRAR_USD = True


# ============================================
# VALIDACION DE CONFIGURACION
# ============================================
def validar_configuracion():
    """Valida que la configuracion minima este completa."""
    errores = []

    if not ODDS_API_KEY:
        errores.append("Falta ODDS_API_KEY en archivo .env")
    if not API_FOOTBALL_KEY:
        errores.append("Falta API_FOOTBALL_KEY en archivo .env")

    if errores:
        logger.warning("Configuracion incompleta detectada:")
        for error in errores:
            logger.warning(f" - {error}")
        logger.info("El sistema funcionara con funcionalidades limitadas")
        return False

    logger.info("Configuracion validada correctamente")
    return True


CONFIG_OK = validar_configuracion()
