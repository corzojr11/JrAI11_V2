import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta

import requests

from config import API_FOOTBALL_KEY, CACHE_TTL_MINUTES, DB_PATH, ODDS_API_KEY
from services.league_service import get_api_football_league_id

BASE_URL = "https://api.the-odds-api.com/v4"
FOOTBALL_API_URL = "https://v3.football.api-sports.io"
CUOTAS_DIR = "cuotas"

os.makedirs(CUOTAS_DIR, exist_ok=True)


def init_cache_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_cache (
            key TEXT PRIMARY KEY,
            response TEXT,
            expires_at TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def get_cache_key(func_name, *args, **kwargs):
    data = f"{func_name}:{args}:{kwargs}".encode()
    return hashlib.md5(data).hexdigest()


def get_from_cache(key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT response, expires_at FROM api_cache WHERE key = ? AND expires_at > ?",
        (key, datetime.now().isoformat()),
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None


def save_to_cache(key, response, ttl_minutes):
    expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (key, response, expires_at) VALUES (?, ?, ?)",
        (key, json.dumps(response, default=str), expires_at),
    )
    conn.commit()
    conn.close()


def cached(ttl_minutes=None):
    def decorator(func):
        def wrapper(*args, **kwargs):
            ttl = ttl_minutes if ttl_minutes is not None else CACHE_TTL_MINUTES
            cache_key = get_cache_key(func.__name__, *args, **kwargs)
            cached_response = get_from_cache(cache_key)
            if cached_response is not None:
                print(f"Usando cache para {func.__name__} (TTL {ttl} min)")
                return cached_response

            result = func(*args, **kwargs)
            if result is not None and ttl > 0:
                save_to_cache(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


def _normalizar_texto(texto):
    return " ".join(
        (texto or "")
        .strip()
        .lower()
        .replace(" vs. ", " vs ")
        .replace(" v ", " vs ")
        .split()
    )


def _coincide_partido(nombre_buscado, home, away):
    nombre_normalizado = _normalizar_texto(nombre_buscado)
    home_normalizado = _normalizar_texto(home)
    away_normalizado = _normalizar_texto(away)
    combinaciones = [
        f"{home_normalizado} {away_normalizado}",
        f"{home_normalizado} vs {away_normalizado}",
        f"{away_normalizado} vs {home_normalizado}",
    ]
    return any(
        nombre_normalizado in combinado or combinado in nombre_normalizado
        for combinado in combinaciones
    )


def _filtrar_bookmakers(partido, bookmaker_filtro=""):
    if not bookmaker_filtro:
        return partido

    filtro = bookmaker_filtro.strip().lower()
    bookmakers = [
        bm
        for bm in partido.get("bookmakers", [])
        if filtro in bm.get("title", "").lower()
    ]
    if not bookmakers:
        return None

    partido_filtrado = dict(partido)
    partido_filtrado["bookmakers"] = bookmakers
    return partido_filtrado


init_cache_db()


def obtener_cuotas_api_football(liga_key, nombre_partido, region="uk", bookmaker_filtro=""):
    """
    Obtiene cuotas de un partido usando API-Football para ligas no cubiertas
    por The Odds API.
    """
    del region

    league_id = get_api_football_league_id(liga_key)
    if not league_id:
        return None, "Liga no soportada en API-Football", []
    if not API_FOOTBALL_KEY:
        return None, "API-Football no configurada", []

    season = 2026
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    today = datetime.now().date()
    fecha_desde = today - timedelta(days=1)
    fecha_hasta = today + timedelta(days=7)
    fixtures_url = f"{FOOTBALL_API_URL}/fixtures"
    params = {
        "league": league_id,
        "season": season,
        "from": fecha_desde.isoformat(),
        "to": fecha_hasta.isoformat(),
    }

    try:
        resp = requests.get(fixtures_url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return None, f"Error API-Football: {resp.status_code}", []

        data = resp.json()
        if not data.get("response"):
            return (
                None,
                f"No hay partidos entre {fecha_desde} y {fecha_hasta} en esta liga (temporada {season})",
                [],
            )

        partidos = data["response"]
        lista_partidos = [
            f"{p['teams']['home']['name']} vs {p['teams']['away']['name']}"
            for p in partidos
        ]

        for partido in partidos:
            home = partido["teams"]["home"]["name"]
            away = partido["teams"]["away"]["name"]
            if not _coincide_partido(nombre_partido, home, away):
                continue

            partido_data = obtener_cuotas_fallback_odds(
                partido["fixture"]["id"],
                bookmaker_filtro=bookmaker_filtro,
            )
            if partido_data:
                archivo = generar_archivo(partido_data)
                return archivo, None, lista_partidos

            if bookmaker_filtro:
                return (
                    None,
                    f"No se encontraron cuotas para la casa '{bookmaker_filtro}'",
                    lista_partidos,
                )
            return None, "No se pudieron obtener las cuotas", lista_partidos

        return None, f"No se encontro '{nombre_partido}'", lista_partidos
    except Exception as e:
        return None, str(e), []


def obtener_cuotas_fallback_odds(fixture_id, bookmaker_filtro=""):
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    odds_url = f"{FOOTBALL_API_URL}/odds"
    params = {"fixture": fixture_id}
    try:
        resp = requests.get(odds_url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data.get("response"):
            return None

        odds_data = data["response"][0]
        partido = {
            "home_team": odds_data["teams"]["home"]["name"],
            "away_team": odds_data["teams"]["away"]["name"],
            "commence_time": odds_data["fixture"]["date"],
            "bookmakers": [],
        }

        for book in odds_data.get("bookmakers", []):
            bookmaker = {"title": book.get("name", "Desconocido"), "markets": []}
            for bet in book.get("bets", []):
                if bet.get("name") != "Match Winner":
                    continue

                market = {"key": "h2h", "outcomes": []}
                for value in bet.get("values", []):
                    market["outcomes"].append(
                        {"name": value.get("value", ""), "price": value.get("odd", 0)}
                    )
                bookmaker["markets"].append(market)

            if bookmaker["markets"]:
                partido["bookmakers"].append(bookmaker)

        return _filtrar_bookmakers(partido, bookmaker_filtro=bookmaker_filtro)
    except Exception as e:
        print(f"Error en obtener_cuotas_fallback_odds: {e}")
        return None


@cached(ttl_minutes=60)
def obtener_ligas_futbol(force_refresh=False):
    del force_refresh

    url = f"{BASE_URL}/sports"
    params = {"apiKey": ODDS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"Error obteniendo ligas: {resp.status_code}")
            return None

        todos = resp.json()
        ligas = [deporte for deporte in todos if deporte.get("group") == "Soccer"]
        ligas.sort(key=lambda x: x.get("title", ""))
        return ligas
    except Exception as e:
        print(f"Error en obtener_ligas_futbol: {e}")
        return None


@cached(ttl_minutes=15)
def obtener_cuotas_de_liga(liga_key, nombre_partido, region="uk", bookmaker_filtro=""):
    """
    Obtiene cuotas. Si la liga esta mapeada a API-Football, usa ese flujo.
    En caso contrario, usa The Odds API.
    """
    ligas_api_football = [
        "soccer_colombia_primera_a",
        "soccer_colombia_primera_b",
        "soccer_uefa_champions_league",
        "soccer_uefa_europa_league",
        "soccer_uefa_conference_league",
        "soccer_conmebol_libertadores",
        "soccer_conmebol_sudamericana",
        "soccer_fifa_world_cup",
        "soccer_conmebol_world_cup_qualifying",
        "soccer_england_championship",
        "soccer_england_league1",
        "soccer_england_league2",
        "soccer_england_fa_cup",
        "soccer_spain_segunda_division",
        "soccer_spain_copa_del_rey",
        "soccer_italy_serie_b",
        "soccer_italy_coppa_italia",
        "soccer_germany_bundesliga_2",
        "soccer_germany_dfb_pokal",
        "soccer_france_ligue_two",
        "soccer_france_coupe_de_france",
        "soccer_brazil_serie_a",
        "soccer_brazil_serie_b",
        "soccer_brazil_copa_do_brasil",
        "soccer_usa_mls",
        "soccer_portugal_primeira_liga",
        "soccer_netherlands_eredivisie",
        "soccer_belgium_first_div",
        "soccer_turkey_super_lig",
        "soccer_greece_super_league",
        "soccer_argentina_primera_division",
    ]
    if liga_key in ligas_api_football:
        return obtener_cuotas_api_football(
            liga_key,
            nombre_partido,
            region=region,
            bookmaker_filtro=bookmaker_filtro,
        )

    url = f"{BASE_URL}/sports/{liga_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": region,
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None, f"Error {resp.status_code} en liga {liga_key}: {resp.text}", []

        partidos = resp.json()
        if not partidos:
            return None, f"No hay partidos proximos en {liga_key}", []

        lista_partidos = [
            f"{partido.get('home_team')} vs {partido.get('away_team')}"
            for partido in partidos
        ]
        for partido in partidos:
            home = partido.get("home_team", "")
            away = partido.get("away_team", "")
            if not _coincide_partido(nombre_partido, home, away):
                continue

            partido_filtrado = _filtrar_bookmakers(
                partido,
                bookmaker_filtro=bookmaker_filtro,
            )
            if partido_filtrado is None:
                return (
                    None,
                    f"No se encontraron cuotas para la casa '{bookmaker_filtro}'",
                    lista_partidos,
                )

            archivo = generar_archivo(partido_filtrado)
            return archivo, None, lista_partidos

        return None, f"No se encontro '{nombre_partido}'", lista_partidos
    except Exception as e:
        return None, f"Error inesperado: {str(e)}", []


@cached(ttl_minutes=15)
def obtener_cuota_de_bookmaker(liga_key, nombre_partido, bookmaker="Betsson", region="eu"):
    url = f"{BASE_URL}/sports/{liga_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": region,
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None, None, None

        partidos = resp.json()
        for partido in partidos:
            home = partido.get("home_team", "")
            away = partido.get("away_team", "")
            if not _coincide_partido(nombre_partido, home, away):
                continue

            for bm in partido.get("bookmakers", []):
                if bookmaker.lower() not in bm.get("title", "").lower():
                    continue

                for market in bm.get("markets", []):
                    if market.get("key") != "h2h":
                        continue

                    outcomes = market.get("outcomes", [])
                    cuota_local = None
                    cuota_empate = None
                    cuota_visit = None
                    for outcome in outcomes:
                        if outcome.get("name") == partido.get("home_team"):
                            cuota_local = outcome.get("price")
                        elif outcome.get("name") == "Draw":
                            cuota_empate = outcome.get("price")
                        elif outcome.get("name") == partido.get("away_team"):
                            cuota_visit = outcome.get("price")
                    return cuota_local, cuota_empate, cuota_visit

        return None, None, None
    except Exception:
        return None, None, None


def generar_archivo(partido):
    home = partido.get("home_team", "Local")
    away = partido.get("away_team", "Visitante")
    commence_time = partido.get("commence_time", "")
    try:
        fecha = datetime.fromisoformat(commence_time.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except Exception:
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    filename = f"cuotas_{home}_vs_{away}.txt".replace(" ", "_").replace("/", "_")
    filepath = os.path.join(CUOTAS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as file:
        file.write(f"# CUOTAS REALES - {home} vs {away}\n")
        file.write(f"Fecha partido: {fecha}\n")
        file.write(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        for bookmaker in partido.get("bookmakers", []):
            nombre = bookmaker.get("title", "Desconocido").upper()
            file.write(f"--- {nombre} ---\n")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                outcomes = market.get("outcomes", [])
                if market_key == "h2h":
                    nombre_mercado = "1X2"
                elif market_key == "spreads":
                    nombre_mercado = "Handicap (spread)"
                elif market_key == "totals":
                    nombre_mercado = "Over/Under"
                else:
                    nombre_mercado = market_key

                for outcome in outcomes:
                    name = outcome.get("name", "")
                    price = outcome.get("price", 0)
                    point = outcome.get("point")
                    if point is not None:
                        file.write(f"{nombre_mercado} - {name} ({point}): {price}\n")
                    else:
                        file.write(f"{nombre_mercado} - {name}: {price}\n")
            file.write("\n")
    return filepath


def obtener_creditos_restantes():
    url = f"{BASE_URL}/sports"
    params = {"apiKey": ODDS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            remaining = resp.headers.get("x-requests-remaining")
            used = resp.headers.get("x-requests-used")
            return {"remaining": remaining, "used": used}, None
        return None, f"Error {resp.status_code}"
    except Exception as e:
        return None, str(e)
