from datetime import datetime, timedelta
import re
import unicodedata
from zoneinfo import ZoneInfo

import requests

from config import API_FOOTBALL_KEY
from services.league_service import detectar_liga_automatica, get_api_football_league_id

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_TIMEOUT = 15
PREFERRED_BOOKMAKERS = ["Bet365", "Pinnacle", "Betano", "Betsson", "1xBet"]
LOCAL_TZ = ZoneInfo("America/Bogota")


def _norm(texto):
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return " ".join(texto.split())


def _headers():
    return {"x-apisports-key": API_FOOTBALL_KEY}


def _api_get(endpoint, params=None):
    if not API_FOOTBALL_KEY:
        return None, "API_FOOTBALL_KEY no configurada"
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                f"{API_FOOTBALL_BASE}{endpoint}",
                headers=_headers(),
                params=params or {},
                timeout=API_TIMEOUT,
            )
            
            # Si es un error transitorio del servidor, intentamos de nuevo
            if resp.status_code in [500, 502, 503, 504] and attempt < max_retries:
                continue

            if resp.status_code != 200:
                error_msg = f"API-Football error HTTP {resp.status_code}"
                try:
                    error_detail = resp.json().get("errors", {})
                    if error_detail:
                        error_msg += f": {error_detail}"
                except:
                    pass
                return None, error_msg

            data = resp.json()
            if not isinstance(data, dict):
                return None, "Respuesta de API no es un objeto JSON valido"

            api_errors = data.get("errors") or {}
            if api_errors:
                if isinstance(api_errors, dict):
                    error_txt = " | ".join(f"{k}: {v}" for k, v in api_errors.items() if v)
                else:
                    error_txt = str(api_errors)
                # Si hay errores en el payload pero hay respuesta parcial, la devolvemos con el error
                return data.get("response", []), error_txt
            
            return data.get("response", []), None

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                continue
            return None, "Timeout agotado tras varios intentos"
        except Exception as e:
            if attempt < max_retries:
                continue
            return None, f"Error de conexion: {str(e)}"
    
    return None, "Fallo desconocido en API"


def _fixture_datetime_local(fecha_iso):
    if not fecha_iso:
        return None
    try:
        return datetime.fromisoformat(str(fecha_iso).replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except Exception:
        return None


def parsear_entrada_partido(texto):
    bruto = str(texto or "").strip()
    if not bruto:
        return {"partido": "", "fecha": "", "fecha_iso": "", "local": "", "visitante": ""}

    fecha = ""
    match_fecha = re.search(r"(\d{2}/\d{2}/\d{4})", bruto)
    if match_fecha:
        fecha = match_fecha.group(1)

    partido = bruto
    if " - " in bruto:
        partes = [p.strip() for p in bruto.split(" - ") if p.strip()]
        partido = partes[0]
        if len(partes) > 1 and not fecha:
            fecha = partes[1]

    local = ""
    visitante = ""
    if " vs " in partido.lower():
        trozos = re.split(r"\s+vs\s+", partido, flags=re.IGNORECASE)
        if len(trozos) == 2:
            local, visitante = trozos[0].strip(), trozos[1].strip()

    fecha_iso = ""
    if fecha:
        try:
            fecha_iso = datetime.strptime(fecha, "%d/%m/%Y").strftime("%Y-%m-%d")
        except Exception:
            fecha_iso = ""

    return {
        "partido": partido,
        "fecha": fecha,
        "fecha_iso": fecha_iso,
        "local": local,
        "visitante": visitante,
    }


def _team_match_score(target, candidate):
    objetivo = _norm(target)
    candidato = _norm(candidate)
    if not objetivo or not candidato:
        return 0
    if objetivo == candidato:
        return 6
    score = 0
    if objetivo in candidato:
        score += 4
    if candidato in objetivo:
        score += 2
    tokens_obj = set(objetivo.split())
    tokens_cand = set(candidato.split())
    comunes = tokens_obj & tokens_cand
    score += len(comunes)
    return score


def _buscar_fixture(partido_texto, fecha_iso="", liga_key=None):
    parsed = parsear_entrada_partido(partido_texto)
    local_obj = _norm(parsed["local"])
    visit_obj = _norm(parsed["visitante"])

    liga_detectada = liga_key or detectar_liga_automatica(parsed["partido"])[0]
    league_id = get_api_football_league_id(liga_detectada) if liga_detectada else None

    fechas_busqueda = []
    if fecha_iso:
        base = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
        fechas_busqueda = [(base + timedelta(days=d)).isoformat() for d in range(-1, 2)]
    else:
        hoy = datetime.now().date()
        fechas_busqueda = [(hoy + timedelta(days=d)).isoformat() for d in range(-2, 5)]

    def _colectar_candidatos(restringir_liga=True):
        candidatos_locales = []
        for fecha in fechas_busqueda:
            params = {"date": fecha}
            if restringir_liga and league_id:
                params["league"] = league_id
                params["season"] = datetime.strptime(fecha, "%Y-%m-%d").year
            response, error = _api_get("/fixtures", params)
            if error or not response:
                continue
            candidatos_locales.extend(response)
        return candidatos_locales

    def _elegir_mejor(candidatos_locales):
        mejor_local = None
        mejor_score_local = -1
        for fixture in candidatos_locales:
            home_name = fixture.get("teams", {}).get("home", {}).get("name", "")
            away_name = fixture.get("teams", {}).get("away", {}).get("name", "")
            score = 0
            score += _team_match_score(parsed["local"], home_name)
            score += _team_match_score(parsed["visitante"], away_name)
            score += max(0, _team_match_score(parsed["local"], away_name) - 2)
            score += max(0, _team_match_score(parsed["visitante"], home_name) - 2)
            if score > mejor_score_local:
                mejor_local = fixture
                mejor_score_local = score
        return mejor_local, mejor_score_local

    candidatos = _colectar_candidatos(restringir_liga=True)
    mejor, mejor_score = _elegir_mejor(candidatos)

    # Fallback: si la liga detectada fue mala o ambigua, buscar sin restringir por liga
    if (not mejor or mejor_score <= 0) and league_id:
        candidatos = _colectar_candidatos(restringir_liga=False)
        mejor, mejor_score = _elegir_mejor(candidatos)

    if not mejor or mejor_score <= 1:
        return None, "No se encontro un fixture coincidente en API-Football. Prueba con nombres mas completos, por ejemplo 'Atletico Nacional vs Llaneros'."
    return mejor, None


def obtener_partidos_por_fecha(fecha_iso, league_id=None, solo_futuros=True):
    """
    Obtiene todos los partidos de una fecha específica.
    
    Args:
        fecha_iso: Fecha en formato YYYY-MM-DD
        league_id: (Opcional) ID de la liga para filtrar
        solo_futuros: Si True, solo devuelve partidos que no se han jugado
    
    Returns:
        Lista de partidos con información básica
    """
    params = {"date": fecha_iso}
    if league_id:
        params["league"] = league_id
        params["season"] = datetime.strptime(fecha_iso, "%Y-%m-%d").year
    
    response, error = _api_get("/fixtures", params)
    
    if error or not response:
        return [], error
    
    partidos = []
    for fixture in response:
        teams = fixture.get("teams", {})
        league = fixture.get("league", {})
        fixture_info = fixture.get("fixture", {})
        
        estado = fixture_info.get("status", {}).get("short")
        
        # Filtrar por estado - solo mostrar partidos no terminados
        if solo_futuros:
            # Estados que significa que el partido YA terminó o está cancelado
            estados_finalizados = ["FT", "POST", "CANC", "INT", "ABR", "AWD", "WO"]
            if estado in estados_finalizados:
                continue
        
        partido = {
            "fixture_id": fixture_info.get("id"),
            "fecha": fixture_info.get("date"),
            "fecha_corta": fixture_info.get("date", "")[:10],
            "hora": fixture_info.get("date", "")[11:16],
            "estado": estado,
            "liga": league.get("name"),
            "liga_id": league.get("id"),
            "local": teams.get("home", {}).get("name"),
            "local_id": teams.get("home", {}).get("id"),
            "visitante": teams.get("away", {}).get("name"),
            "visitante_id": teams.get("away", {}).get("id"),
            "goles_local": teams.get("home", {}).get("score", {}).get("full"),
            "goles_visitante": teams.get("away", {}).get("score", {}).get("full"),
            "logo_local": teams.get("home", {}).get("logo"),
            "logo_visitante": teams.get("away", {}).get("logo"),
        }
        partidos.append(partido)
    
    return partidos, None


def obtener_partidos_proximos(dias_adelante=3):
    """
    Obtiene los partidos de los próximos X días que aún no se han jugado.
    Busca desde ayer hasta dias_adelante para cubrir zonas horarias.
    
    Args:
        dias_adelante: Número de días hacia adelante a buscar
    
    Returns:
        Lista de partidos futuros
    """
    todos_partidos = []
    
    # Buscar desde ayer para cubrir partidos que en UTC ya pasaron pero en local no
    for dia in range(-1, dias_adelante + 1):
        fecha = (datetime.now() + timedelta(days=dia)).date()
        fecha_iso = fecha.isoformat()
        
        partidos, error = obtener_partidos_por_fecha(fecha_iso, solo_futuros=True)
        
        if not error and partidos:
            todos_partidos.extend(partidos)
    
    # Ordenar por fecha/hora
    todos_partidos.sort(key=lambda x: x.get("fecha", ""))
    
    return todos_partidos, None


def obtener_partidos_por_fecha_local(fecha_iso, league_id=None, solo_futuros=True):
    try:
        fecha_obj = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
    except Exception:
        return [], "Fecha invalida"

    ahora_local = datetime.now(LOCAL_TZ)
    partidos = []
    vistos = set()
    errores = []
    for offset in (-1, 0, 1):
        fecha_busqueda = (fecha_obj + timedelta(days=offset)).isoformat()
        params = {"date": fecha_busqueda}
        if league_id:
            params["league"] = league_id
            params["season"] = datetime.strptime(fecha_busqueda, "%Y-%m-%d").year
        response, error = _api_get("/fixtures", params)
        if error:
            errores.append(error)
            continue
        for fixture in response or []:
            fixture_info = fixture.get("fixture", {})
            fixture_id = fixture_info.get("id")
            if fixture_id in vistos:
                continue
            dt_local = _fixture_datetime_local(fixture_info.get("date"))
            if not dt_local or dt_local.date() != fecha_obj:
                continue
            estado = fixture_info.get("status", {}).get("short")
            if estado in ["FT", "AET", "PEN", "POST", "CANC", "INT", "ABR", "AWD", "WO"]:
                continue
            if solo_futuros and dt_local <= ahora_local:
                continue

            teams = fixture.get("teams", {})
            league = fixture.get("league", {})
            partidos.append(
                {
                    "fixture_id": fixture_id,
                    "fecha": fixture_info.get("date"),
                    "fecha_corta": dt_local.strftime("%Y-%m-%d"),
                    "hora": dt_local.strftime("%H:%M"),
                    "estado": estado,
                    "liga": league.get("name"),
                    "liga_id": league.get("id"),
                    "local": teams.get("home", {}).get("name"),
                    "local_id": teams.get("home", {}).get("id"),
                    "visitante": teams.get("away", {}).get("name"),
                    "visitante_id": teams.get("away", {}).get("id"),
                    "goles_local": teams.get("home", {}).get("score", {}).get("full"),
                    "goles_visitante": teams.get("away", {}).get("score", {}).get("full"),
                    "logo_local": teams.get("home", {}).get("logo"),
                    "logo_visitante": teams.get("away", {}).get("logo"),
                }
            )
            vistos.add(fixture_id)

    partidos.sort(key=lambda x: x.get("fecha", ""))
    return partidos, errores[0] if (not partidos and errores) else None


def obtener_partidos_proximos_locales(dias_adelante=3):
    todos_partidos = []
    for dia in range(0, dias_adelante + 1):
        fecha = (datetime.now(LOCAL_TZ) + timedelta(days=dia)).date().isoformat()
        partidos, error = obtener_partidos_por_fecha_local(fecha, solo_futuros=True)
        if not error and partidos:
            todos_partidos.extend(partidos)
    todos_partidos.sort(key=lambda x: x.get("fecha", ""))
    return todos_partidos, None


def _team_statistics(team_id, league_id, season):
    response, error = _api_get("/teams/statistics", {"team": team_id, "league": league_id, "season": season})
    if error or not response:
        return {}
    if isinstance(response, list):
        data = response[0] if response else {}
    else:
        data = response
    return data or {}


def buscar_logo_equipo(team_name):
    nombre = str(team_name or "").strip()
    if not nombre:
        return ""
    response, error = _api_get("/teams", {"search": nombre})
    if error or not response:
        return ""
    objetivo = _norm(nombre)
    mejor_logo = ""
    mejor_score = -1
    for item in response:
        team = item.get("team", {}) if isinstance(item, dict) else {}
        candidato = str(team.get("name", "") or "").strip()
        logo = str(team.get("logo", "") or "").strip()
        if not candidato or not logo:
            continue
        cand_norm = _norm(candidato)
        score = 0
        if cand_norm == objetivo:
            score += 3
        if objetivo and objetivo in cand_norm:
            score += 2
        if cand_norm and cand_norm in objetivo:
            score += 1
        if score > mejor_score:
            mejor_logo = logo
            mejor_score = score
    return mejor_logo


def _recent_fixtures(team_id, league_id, season, last=5):
    response, error = _api_get(
        "/fixtures",
        {"team": team_id, "league": league_id, "season": season, "last": last},
    )
    if error or not response:
        response, error = _api_get("/fixtures", {"team": team_id, "last": last})
        if error or not response:
            return []
    return response


def _season_fixtures(team_id, league_id, season):
    response, error = _api_get(
        "/fixtures",
        {"team": team_id, "league": league_id, "season": season, "status": "FT"},
    )
    if error or not response:
        response, error = _api_get("/fixtures", {"team": team_id, "last": 20})
        if error or not response:
            return []
    return response


def _fixture_statistics(fixture_id):
    response, error = _api_get("/fixtures/statistics", {"fixture": fixture_id})
    if error or not response:
        return []
    return response


def _aggregate_recent_stats(team_id, fixtures):
    totales = {
        "shots_on_goal": 0.0,
        "shots_total": 0.0,
        "corners": 0.0,
        "yellow": 0.0,
        "red": 0.0,
        "possession": 0.0,
        "fouls": 0.0,
        "count": 0,
    }
    resultados = []
    for item in fixtures:
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")
        target_side = None
        rival = ""
        marcador = ""
        if team_id == home_id:
            target_side = "home"
            rival = teams.get("away", {}).get("name", "")
            marcador = f"{goals.get('home', 0)}-{goals.get('away', 0)}"
        elif team_id == away_id:
            target_side = "away"
            rival = teams.get("home", {}).get("name", "")
            marcador = f"{goals.get('away', 0)}-{goals.get('home', 0)}"
        resultados.append(
            {
                "fecha": fixture.get("date", "")[:10],
                "rival": rival,
                "marcador": marcador,
                "estado": fixture.get("status", {}).get("short", ""),
            }
        )

        stats_response = _fixture_statistics(fixture.get("id"))
        if not stats_response or not target_side:
            continue
        team_stats = None
        for stat in stats_response:
            if stat.get("team", {}).get("id") == team_id:
                team_stats = stat.get("statistics", [])
                break
        if not team_stats:
            continue

        def _get_stat(nombre):
            for s in team_stats:
                if str(s.get("type", "")).strip().lower() == nombre.lower():
                    valor = s.get("value", 0)
                    if valor in (None, ""):
                        return 0
                    if isinstance(valor, str):
                        valor = valor.replace("%", "").strip()
                    try:
                        return float(valor)
                    except Exception:
                        return 0
            return 0

        totales["shots_on_goal"] += _get_stat("Shots on Goal")
        totales["shots_total"] += _get_stat("Total Shots")
        totales["corners"] += _get_stat("Corner Kicks")
        totales["yellow"] += _get_stat("Yellow Cards")
        totales["red"] += _get_stat("Red Cards")
        totales["possession"] += _get_stat("Ball Possession")
        totales["fouls"] += _get_stat("Fouls")
        totales["count"] += 1

    if totales["count"]:
        for key in ("shots_on_goal", "shots_total", "corners", "yellow", "red", "possession", "fouls"):
            totales[key] = round(totales[key] / totales["count"], 2)
    return {"promedios": totales, "resultados": resultados}


def _season_percentages(team_id, fixtures):
    total = 0
    over25 = 0
    btts = 0
    for item in fixtures:
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")
        if team_id not in {home_id, away_id}:
            continue
        home_goals = int(goals.get("home", 0) or 0)
        away_goals = int(goals.get("away", 0) or 0)
        total += 1
        if home_goals + away_goals > 2:
            over25 += 1
        if home_goals > 0 and away_goals > 0:
            btts += 1
    if total == 0:
        return {"over25_pct": 0.0, "btts_pct": 0.0}
    return {
        "over25_pct": round((over25 / total) * 100, 2),
        "btts_pct": round((btts / total) * 100, 2),
    }


def _head_to_head(home_id, away_id, last=5):
    response, error = _api_get("/fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": last})
    if error or not response:
        response, error = _api_get("/fixtures/headtohead", {"h2h": f"{away_id}-{home_id}", "last": last})
    if error or not response:
        return []
    resumen = []
    for item in response:
        resumen.append(
            {
                "fecha": item.get("fixture", {}).get("date", "")[:10],
                "partido": f"{item.get('teams', {}).get('home', {}).get('name', '')} vs {item.get('teams', {}).get('away', {}).get('name', '')}",
                "marcador": f"{item.get('goals', {}).get('home', 0)}-{item.get('goals', {}).get('away', 0)}",
            }
        )
    return resumen


def _standings(league_id, season):
    response, error = _api_get("/standings", {"league": league_id, "season": season})
    if error or not response:
        return []
    bloques = response[0].get("league", {}).get("standings", []) if response else []
    return bloques[0] if bloques else []


def _find_standing(team_id, standings):
    for row in standings:
        if row.get("team", {}).get("id") == team_id:
            return {
                "pos": row.get("rank"),
                "puntos": row.get("points"),
                "pj": row.get("all", {}).get("played"),
                "g": row.get("all", {}).get("win"),
                "e": row.get("all", {}).get("draw"),
                "p": row.get("all", {}).get("lose"),
                "gf": row.get("all", {}).get("goals", {}).get("for"),
                "gc": row.get("all", {}).get("goals", {}).get("against"),
                "forma": row.get("form", ""),
            }
    return {}


def _injuries(team_id, league_id, season):
    response, error = _api_get("/injuries", {"team": team_id, "league": league_id, "season": season})
    if error or not response:
        return []
    lista = []
    for item in response[:8]:
        player = item.get("player", {})
        fixture = item.get("fixture", {})
        lista.append(
            {
                "jugador": player.get("name", ""),
                "tipo": item.get("type", ""),
                "razon": item.get("reason", ""),
                "fecha": fixture.get("date", "")[:10],
            }
        )
    return lista


def _lineups(fixture_id):
    response, error = _api_get("/fixtures/lineups", {"fixture": fixture_id})
    if error or not response:
        return []

    def _player_name(entry):
        if not isinstance(entry, dict):
            return ""
        player = entry.get("player")
        if isinstance(player, dict):
            return str(player.get("name", "") or "").strip()
        # Fallbacks por si la API cambia ligeramente la forma.
        return str(
            entry.get("name")
            or entry.get("player_name")
            or entry.get("fullname")
            or ""
        ).strip()

    lineups = []
    for item in response:
        titulares = [_player_name(j) for j in item.get("startXI", [])[:11]]
        titulares = [x for x in titulares if x]
        suplentes = [_player_name(j) for j in item.get("substitutes", [])[:12]]
        suplentes = [x for x in suplentes if x]
        formacion = str(item.get("formation", "") or "").strip()
        if formacion.lower() == "none":
            formacion = ""
        lineups.append(
            {
                "equipo": item.get("team", {}).get("name", ""),
                "formacion": formacion,
                "titulares": titulares,
                "suplentes": suplentes,
            }
        )
    return lineups


def _lineups_have_real_data(lineups):
    for item in lineups or []:
        formacion = str(item.get("formacion", "") or "").strip().lower()
        titulares = [str(x or "").strip() for x in item.get("titulares", []) if str(x or "").strip()]
        if formacion and formacion != "none":
            return True
        if len(titulares) >= 6:
            return True
    return False


def _odds(fixture_id):
    response, error = _api_get("/odds", {"fixture": fixture_id})
    if error or not response:
        return {"bookmakers": [], "resumen": {}}

    respuesta = response[0] if response else {}
    bookmakers = []
    resumen = {"1X2": [], "Over/Under": [], "BTTS": [], "Handicap": [], "Corners": [], "Tarjetas": []}

    for book in respuesta.get("bookmakers", []):
        nombre_book = book.get("name", "Desconocido")
        mercados = []
        for bet in book.get("bets", []):
            bet_name = str(bet.get("name", "")).strip()
            values = bet.get("values", [])
            if not values:
                continue
            mercados.append({"mercado": bet_name, "valores": values})
            if bet_name == "Match Winner":
                resumen["1X2"].append({"bookmaker": nombre_book, "valores": values})
            elif "Both Teams Score" in bet_name:
                resumen["BTTS"].append({"bookmaker": nombre_book, "valores": values})
            elif "Goals Over/Under" in bet_name:
                resumen["Over/Under"].append({"bookmaker": nombre_book, "valores": values})
            elif "Asian Handicap" in bet_name:
                resumen["Handicap"].append({"bookmaker": nombre_book, "valores": values})
            elif "Corner" in bet_name:
                resumen["Corners"].append({"bookmaker": nombre_book, "valores": values})
            elif "Card" in bet_name:
                resumen["Tarjetas"].append({"bookmaker": nombre_book, "valores": values})
        if mercados:
            bookmakers.append({"bookmaker": nombre_book, "mercados": mercados})
    for mercado_key, items in resumen.items():
        items.sort(
            key=lambda item: (
                0 if item.get("bookmaker", "") in PREFERRED_BOOKMAKERS else 1,
                PREFERRED_BOOKMAKERS.index(item.get("bookmaker", "")) if item.get("bookmaker", "") in PREFERRED_BOOKMAKERS else 999,
                item.get("bookmaker", ""),
            )
        )
    bookmakers.sort(
        key=lambda item: (
            0 if item.get("bookmaker", "") in PREFERRED_BOOKMAKERS else 1,
            PREFERRED_BOOKMAKERS.index(item.get("bookmaker", "")) if item.get("bookmaker", "") in PREFERRED_BOOKMAKERS else 999,
            item.get("bookmaker", ""),
        )
    )
    return {"bookmakers": bookmakers, "resumen": resumen}


def _safe_avg(value):
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _build_team_block(team_name, stats, recent_stats, standing, injuries, season_pct):
    goals = stats.get("goals", {})
    promedio_for = goals.get("for", {}).get("average", {}).get("total")
    promedio_against = goals.get("against", {}).get("average", {}).get("total")
    cards = stats.get("cards", {})
    amarillas = 0
    rojas = 0
    for minuto in cards.get("yellow", {}).values():
        amarillas += float(minuto.get("total", 0) or 0)
    for minuto in cards.get("red", {}).values():
        rojas += float(minuto.get("total", 0) or 0)
    played = max(1, int(stats.get("fixtures", {}).get("played", {}).get("total", 0) or 0))

    goles_favor = _safe_avg(promedio_for)
    goles_contra = _safe_avg(promedio_against)
    if not goles_favor and standing.get("gf") is not None and standing.get("pj"):
        try:
            goles_favor = round(float(standing.get("gf", 0)) / max(1, float(standing.get("pj", 0))), 2)
        except Exception:
            goles_favor = 0.0
    if not goles_contra and standing.get("gc") is not None and standing.get("pj"):
        try:
            goles_contra = round(float(standing.get("gc", 0)) / max(1, float(standing.get("pj", 0))), 2)
        except Exception:
            goles_contra = 0.0

    return {
        "equipo": team_name,
        "goles_favor": goles_favor,
        "goles_contra": goles_contra,
        "shots_on_goal": recent_stats.get("promedios", {}).get("shots_on_goal", 0.0),
        "shots_total": recent_stats.get("promedios", {}).get("shots_total", 0.0),
        "corners": recent_stats.get("promedios", {}).get("corners", 0.0),
        "yellow": round(amarillas / played, 2) if played else 0.0,
        "red": round(rojas / played, 2) if played else 0.0,
        "possession": recent_stats.get("promedios", {}).get("possession", 0.0),
        "fouls": recent_stats.get("promedios", {}).get("fouls", 0.0),
        "over25_pct": season_pct.get("over25_pct", 0.0),
        "btts_pct": season_pct.get("btts_pct", 0.0),
        "forma": recent_stats.get("resultados", []),
        "tabla": standing,
        "lesiones": injuries,
    }


def preparar_partido_desde_api(partido_texto, fecha_iso="", liga_key=None):
    fixture, error = _buscar_fixture(partido_texto, fecha_iso=fecha_iso, liga_key=liga_key)
    if error:
        return None, error

    fixture_id = fixture.get("fixture", {}).get("id")
    league = fixture.get("league", {})
    league_id = league.get("id")
    season = league.get("season")
    home = fixture.get("teams", {}).get("home", {})
    away = fixture.get("teams", {}).get("away", {})
    home_id = home.get("id")
    away_id = away.get("id")

    home_stats = _team_statistics(home_id, league_id, season)
    away_stats = _team_statistics(away_id, league_id, season)
    recent_home = _recent_fixtures(home_id, league_id, season, last=5)
    recent_away = _recent_fixtures(away_id, league_id, season, last=5)
    season_home = _season_fixtures(home_id, league_id, season)
    season_away = _season_fixtures(away_id, league_id, season)
    recent_home_stats = _aggregate_recent_stats(home_id, recent_home)
    recent_away_stats = _aggregate_recent_stats(away_id, recent_away)
    season_home_pct = _season_percentages(home_id, season_home)
    season_away_pct = _season_percentages(away_id, season_away)
    h2h = _head_to_head(home_id, away_id, last=5)
    standings = _standings(league_id, season)
    home_standing = _find_standing(home_id, standings)
    away_standing = _find_standing(away_id, standings)
    home_injuries = _injuries(home_id, league_id, season)
    away_injuries = _injuries(away_id, league_id, season)
    lineups = _lineups(fixture_id)
    odds = _odds(fixture_id)
    standings_err = None
    home_stats_err = None
    away_stats_err = None
    recent_home_err = None
    recent_away_err = None
    h2h_err = None
    inj_home_err = None
    inj_away_err = None
    lineup_err = None
    odds_err = None

    lineups_ok = _lineups_have_real_data(lineups)

    debug_api = {
        "fixture": {"ok": bool(fixture_id), "detalle": str(fixture_id or "")},
        "tabla": {"ok": bool(standings), "detalle": standings_err or f"{len(standings)} filas"},
        "stats_local": {"ok": bool(home_stats), "detalle": home_stats_err or f"{len(home_stats.keys()) if isinstance(home_stats, dict) else 0} claves"},
        "stats_visitante": {"ok": bool(away_stats), "detalle": away_stats_err or f"{len(away_stats.keys()) if isinstance(away_stats, dict) else 0} claves"},
        "forma_local": {"ok": bool(recent_home_stats.get('resultados')), "detalle": recent_home_err or f"{len(recent_home_stats.get('resultados', []))} partidos"},
        "forma_visitante": {"ok": bool(recent_away_stats.get('resultados')), "detalle": recent_away_err or f"{len(recent_away_stats.get('resultados', []))} partidos"},
        "h2h": {"ok": bool(h2h), "detalle": h2h_err or f"{len(h2h)} partidos"},
        "lesiones_local": {"ok": bool(home_injuries), "detalle": inj_home_err or f"{len(home_injuries)} registros"},
        "lesiones_visitante": {"ok": bool(away_injuries), "detalle": inj_away_err or f"{len(away_injuries)} registros"},
        "alineaciones": {"ok": lineups_ok, "detalle": lineup_err or ("Sin formacion/titulares utiles" if lineups and not lineups_ok else f"{len(lineups)} equipos")},
        "odds": {"ok": bool(odds.get('bookmakers')), "detalle": odds_err or f"{len(odds.get('bookmakers', []))} bookmakers"},
    }

    return {
        "fixture_id": fixture_id,
        "partido": f"{home.get('name', '')} vs {away.get('name', '')}",
        "fecha": fixture.get("fixture", {}).get("date", "")[:10],
        "hora": fixture.get("fixture", {}).get("date", "")[11:16],
        "estadio": fixture.get("fixture", {}).get("venue", {}).get("name", ""),
        "ciudad": fixture.get("fixture", {}).get("venue", {}).get("city", ""),
        "arbitro": fixture.get("fixture", {}).get("referee", "") or "",
        "liga_key": liga_key or detectar_liga_automatica(partido_texto)[0],
        "liga_nombre": league.get("name", ""),
        "pais": league.get("country", ""),
        "temporada": season,
        "home": _build_team_block(home.get("name", ""), home_stats, recent_home_stats, home_standing, home_injuries, season_home_pct),
        "away": _build_team_block(away.get("name", ""), away_stats, recent_away_stats, away_standing, away_injuries, season_away_pct),
        "h2h": h2h,
        "lineups": lineups,
        "odds": odds,
        "debug_api": debug_api,
    }, None


def _format_lista_resultados(items):
    if not items:
        return "- Sin datos"
    return "\n".join(
        f"- {i.get('fecha', '')}: vs {i.get('rival', '')} | {i.get('marcador', '')}"
        for i in items
    )


def _format_h2h(items):
    if not items:
        return "- Sin datos"
    return "\n".join(
        f"- {i.get('fecha', '')}: {i.get('partido', '')} | {i.get('marcador', '')}"
        for i in items
    )


def _format_injuries(items):
    if not items:
        return "- Sin bajas confirmadas en API"
    return "\n".join(
        f"- {i.get('jugador', '')}: {i.get('tipo', '')} | {i.get('razon', '')}"
        for i in items
    )


def _format_lineups(lineups, team_name):
    for item in lineups:
        if _norm(item.get("equipo", "")) == _norm(team_name):
            titulares = ", ".join([x for x in item.get("titulares", []) if x])
            formacion = str(item.get("formacion", "") or "").strip() or "Sin formacion confirmada"
            return f"Formacion: {formacion}\nTitulares: {titulares or 'Sin titulares confirmados'}"
    return "Sin alineacion probable disponible"


def _format_manual_block(texto, default_text):
    limpio = str(texto or "").strip()
    return limpio if limpio else default_text


def _format_odds_summary(odds_data):
    resumen = odds_data.get("resumen", {}) if odds_data else {}
    bloques = []
    for clave in ("1X2", "Over/Under", "BTTS", "Handicap", "Corners", "Tarjetas"):
        mercados = resumen.get(clave, [])
        if not mercados:
            bloques.append(f"{clave}: sin datos")
            continue
        primera = mercados[0]
        valores = primera.get("valores", [])[:6]
        valores_txt = ", ".join(f"{v.get('value', '')} @ {v.get('odd', '')}" for v in valores)
        bloques.append(f"{clave} ({primera.get('bookmaker', '')}): {valores_txt}")
    return "\n".join(f"- {b}" for b in bloques)


def construir_ficha_preparada(data, manual):
    home = data.get("home", {})
    away = data.get("away", {})
    manual = manual or {}

    arbitro_final = manual.get("arbitro_manual", "") or data.get("arbitro", "")
    lesiones_local = _format_injuries(home.get("lesiones", []))
    lesiones_visit = _format_injuries(away.get("lesiones", []))
    if manual.get("lesiones_local_manual"):
        lesiones_local = _format_manual_block(manual.get("lesiones_local_manual"), "- Sin bajas reportadas")
    if manual.get("lesiones_visitante_manual"):
        lesiones_visit = _format_manual_block(manual.get("lesiones_visitante_manual"), "- Sin bajas reportadas")

    lineup_local = _format_lineups(data.get("lineups", []), home.get("equipo", ""))
    lineup_visit = _format_lineups(data.get("lineups", []), away.get("equipo", ""))
    if manual.get("alineacion_local_manual"):
        lineup_local = _format_manual_block(manual.get("alineacion_local_manual"), "Sin alineacion probable disponible")
    if manual.get("alineacion_visitante_manual"):
        lineup_visit = _format_manual_block(manual.get("alineacion_visitante_manual"), "Sin alineacion probable disponible")

    odds_txt = _format_odds_summary(data.get("odds", {}))
    if manual.get("cuotas_manual_resumen"):
        odds_txt = _format_manual_block(manual.get("cuotas_manual_resumen"), "- Sin cuotas disponibles")

    forma_local_txt = manual.get("forma_local_manual", "").strip() or _format_lista_resultados(home.get("forma", []))
    forma_visit_txt = manual.get("forma_visitante_manual", "").strip() or _format_lista_resultados(away.get("forma", []))
    h2h_txt = manual.get("h2h_manual", "").strip() or _format_h2h(data.get("h2h", []))

    return f"""## DATOS GENERALES
- Partido: {data.get('partido', '')}
- Competicion: {data.get('liga_nombre', '')} ({data.get('pais', '')})
- Fecha y hora: {data.get('fecha', '')} {data.get('hora', '')}
- Estadio: {data.get('estadio', '')} - {data.get('ciudad', '')}
- Arbitro: {arbitro_final or 'Sin arbitro confirmado'}

## BLOQUE 1 — DATOS BASE DE TEMPORADA
- {home.get('equipo', '')}: GF {home.get('goles_favor', 0)} | GC {home.get('goles_contra', 0)} | % Over 2.5 {home.get('over25_pct', 0)} | % BTTS {home.get('btts_pct', 0)} | Tiros a puerta {home.get('shots_on_goal', 0)} | Tiros totales {home.get('shots_total', 0)} | Corners {home.get('corners', 0)} | Posesion {home.get('possession', 0)} | Amarillas {home.get('yellow', 0)} | Rojas {home.get('red', 0)}
- {away.get('equipo', '')}: GF {away.get('goles_favor', 0)} | GC {away.get('goles_contra', 0)} | % Over 2.5 {away.get('over25_pct', 0)} | % BTTS {away.get('btts_pct', 0)} | Tiros a puerta {away.get('shots_on_goal', 0)} | Tiros totales {away.get('shots_total', 0)} | Corners {away.get('corners', 0)} | Posesion {away.get('possession', 0)} | Amarillas {away.get('yellow', 0)} | Rojas {away.get('red', 0)}

## BLOQUE 2 — TABLA Y FORMA
- {home.get('equipo', '')}: Pos {home.get('tabla', {}).get('pos', '')} | Pts {home.get('tabla', {}).get('puntos', '')} | PJ {home.get('tabla', {}).get('pj', '')} | G/E/P {home.get('tabla', {}).get('g', '')}/{home.get('tabla', {}).get('e', '')}/{home.get('tabla', {}).get('p', '')} | Forma {home.get('tabla', {}).get('forma', '')}
- {away.get('equipo', '')}: Pos {away.get('tabla', {}).get('pos', '')} | Pts {away.get('tabla', {}).get('puntos', '')} | PJ {away.get('tabla', {}).get('pj', '')} | G/E/P {away.get('tabla', {}).get('g', '')}/{away.get('tabla', {}).get('e', '')}/{away.get('tabla', {}).get('p', '')} | Forma {away.get('tabla', {}).get('forma', '')}

### Ultimos 5 resultados {home.get('equipo', '')}
{forma_local_txt}

### Ultimos 5 resultados {away.get('equipo', '')}
{forma_visit_txt}

## BLOQUE 3 — H2H ULTIMOS 5
{h2h_txt}

## BLOQUE 4 — LESIONES Y SUSPENSIONES
### {home.get('equipo', '')}
{lesiones_local}

### {away.get('equipo', '')}
{lesiones_visit}

## BLOQUE 5 — ALINEACIONES PROBABLES
### {home.get('equipo', '')}
{lineup_local}

### {away.get('equipo', '')}
{lineup_visit}

## BLOQUE 6 — CUOTAS DE REFERENCIA
{odds_txt}

## BLOQUE 7 — DATOS MANUALES CLAVE
- xG local: {manual.get('xg_local', '')}
- xG visitante: {manual.get('xg_visitante', '')}
- ELO local: {manual.get('elo_local', '')}
- ELO visitante: {manual.get('elo_visitante', '')}
- Motivacion local: {manual.get('motivacion_local', '')}
- Motivacion visitante: {manual.get('motivacion_visitante', '')}
- Contexto adicional: {manual.get('contexto_extra', '')}

## ALERTAS DE CALIDAD DE DATOS
- Campo xG: {'Completo' if manual.get('xg_local') and manual.get('xg_visitante') else 'Pendiente de completar'}
- Campo ELO: {'Completo' if manual.get('elo_local') and manual.get('elo_visitante') else 'Pendiente de completar'}
- Contexto motivacional: {'Completo' if manual.get('motivacion_local') or manual.get('motivacion_visitante') else 'Pendiente de completar'}
""".strip()
