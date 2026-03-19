# config.py
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# Configurar logging para no mostrar informacion sensible en consola
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURACION PRINCIPAL
# ============================================
STAKE_PORCENTAJE = 2.0
BANKROLL_INICIAL_COP = 4_000_000
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "data" / "backtest.db")
CACHE_TTL_MINUTES = 5
ENV_PATH = BASE_DIR / ".env"

# Cargar siempre el .env de esta app, sin depender del directorio actual
load_dotenv(dotenv_path=ENV_PATH)

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
# TIPO DE CAMBIO USD/COP
# ============================================
def obtener_tipo_cambio_usd_cop():
    """Obtiene el tipo de cambio actual USD/COP de forma segura."""
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if "rates" in data and "COP" in data["rates"]:
                return data["rates"]["COP"]
    except Exception as e:
        logger.warning(f"Error obteniendo tipo de cambio: {e}. Usando valor por defecto.")

    return 4000


USD_TO_COP = obtener_tipo_cambio_usd_cop()
logger.info(f"Tipo de cambio USD/COP configurado: {USD_TO_COP:.2f}")


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
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()


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
