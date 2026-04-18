"""
Funciones utilitarias de la app.
"""
import os
from pathlib import Path


PROMPT_AUTOMATICO_FALLBACK = """Eres un analista deportivo especializado en futbol y apuestas.

Debes leer el analisis base del Investigador y devolver SOLO un JSON valido.
No devuelvas markdown.
No expliques nada fuera del JSON.

Tu respuesta DEBE seguir esta estructura exacta:
{
  "partido": "Local vs Visitante",
  "fecha": "YYYY-MM-DD o texto si no aparece exacta",
  "mercado": "1X2 | Over 2.5 | Under 2.5 | BTTS | Handicap | Corners | Tarjetas | Sin mercado",
  "seleccion": "texto de la seleccion o NO BET",
  "cuota": 0.0,
  "confianza": 0.00,
  "ev": 0.00,
  "stake": "0u | 0.5u | 1u | 1.5u | 2u | 3u",
  "sistemas_favor": 0,
  "sistemas_total": 8,
  "veredictos_sistemas": {
    "poisson": "apoya|neutral|no_apoya|no_disponible",
    "dixon_coles": "apoya|neutral|no_apoya|no_disponible",
    "elo": "apoya|neutral|no_apoya|no_disponible",
    "regresion_xg": "apoya|neutral|no_apoya|no_disponible",
    "forma_ponderada": "apoya|neutral|no_apoya|no_disponible",
    "arbitraje_lineas": "apoya|neutral|no_apoya|no_disponible",
    "mercado_eficiente": "apoya|neutral|no_apoya|no_disponible",
    "contexto": "apoya|neutral|no_apoya|no_disponible"
  },
  "fundamentos_clave": [
    "fundamento 1",
    "fundamento 2",
    "fundamento 3"
  ],
  "riesgo_principal": "principal riesgo del analisis",
  "razonamiento": "explicacion breve pero concreta",
  "decision": "PICK o NO BET"
}

Reglas:
- No inventes datos que no aparezcan en el analisis base.
- Si faltan datos, reflejalo en `veredictos_sistemas`, `fundamentos_clave` y `riesgo_principal`.
- Siempre llena `veredictos_sistemas` con las 8 claves, aunque algunas sean `no_disponible`.
- Siempre entrega al menos 3 `fundamentos_clave`.
- Si decides `NO BET`, igualmente debes completar todos los campos estructurales.
- Si decides `PICK`, debes ser coherente:
  - `cuota` > 1.01
  - `confianza` entre 0.65 y 1.0
  - `ev` > 0
  - `sistemas_favor` >= 5
- Si decides `NO BET`, puedes usar:
  - `seleccion`: "NO BET"
  - `mercado`: "Sin mercado" o el mercado evaluado
  - `stake`: "0u"

Analisis base del Investigador:
[resumen compacto del investigador]
"""


import re

def normalizar_linea_25(linea_raw):
    """Extrae y valida que la línea sea exactamente 2.5."""
    try:
        if linea_raw is None:
            return None
        # Limpiar string de comas si vienen en formato europeo
        s = str(linea_raw).replace(",", ".")
        # Buscar el primer número flotante
        match = re.search(r"(\d+\.\d+)", s)
        if match:
            valor = float(match.group(1))
            return valor if valor == 2.5 else None
        # Intentar conversión directa si es número puro
        valor = float(s)
        return valor if valor == 2.5 else None
    except (ValueError, TypeError):
        return None

def es_mercado_clv_valido(mercado_original):
    """Valida si el mercado está en el alcance pre-match 1X2 o O/U 2.5."""
    m = str(mercado_original or "").upper()
    es_1x2 = any(x in m for x in ["1X2", "RESULTADO FINAL", "MATCH ODDS", "GANADOR"])
    es_ou = any(x in m for x in ["OVER/UNDER", "O/U", "TOTAL DE GOLES", "GOLES TOTALES"])
    return "1X2" if es_1x2 else ("OU25" if es_ou else None)

def normalizar_seleccion_canonica(seleccion_raw, mercado_tipo):
    """
    Normaliza la selección a un valor canónico según el tipo de mercado.
    1X2 -> 'HOME', 'AWAY', 'DRAW'
    OU25 -> 'OVER', 'UNDER'
    """
    if not seleccion_raw or not mercado_tipo:
        return None
        
    s = str(seleccion_raw).strip().lower()
    
    if mercado_tipo == "1X2":
        if s in ["1", "home", "local", "h", "home team", "1.0", "home_team"]:
            return "HOME"
        if s in ["2", "away", "visitante", "v", "away team", "visit", "2.0", "away_team"]:
            return "AWAY"
        if s in ["x", "draw", "empate", "d"]:
            return "DRAW"
            
    elif mercado_tipo == "OU25":
        # Evitar falsos positivos: si dice "over" es OVER, si dice "under" es UNDER.
        if "over" in s or "mas" in s or "más" in s or s == "o" or s == ">2.5":
            return "OVER"
        if "under" in s or "menos" in s or s == "u" or s == "<2.5":
            return "UNDER"
            
    return None


def normalizar_nombre_equipo_v2(nombre):
    """
    Normaliza el nombre de un equipo para comparación conservadora.
    Elimina solo ruido técnico extremo para preservar identidad (City, United, Real, etc).
    """
    import unicodedata
    if not nombre: return set()
    
    # 1. Quitar acentos y minúsculas
    s = unicodedata.normalize('NFD', str(nombre)).encode('ascii', 'ignore').decode('utf-8').lower()
    # 2. Solo letras y números
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    
    # 3. Stop Words CONSERVADORAS (Solo abreviaturas técnicas que no distinguen equipos)
    # NO incluimos: real, city, united, athletic, atletico, st, club, deportivo.
    noise = {'fc', 'cf', 'cd', 'sc', 'sd', 'ud', 'fk', 'afc', 'de', 'deportivo'}
    
    tokens = {word for word in s.split() if len(word) > 1 and word not in noise}
    return tokens if tokens else {word for word in s.split() if len(word) > 1}

def son_partidos_identicos_v2(partido_pick, home_api, away_api):
    """
    Compara un partido de pick contra uno de API con lógica de tokens conservadora.
    Maneja variantes "vs", " - ", " v ".
    """
    # 1. Split robusto del pick
    partido_pick = str(partido_pick or "")
    separadores = [" vs ", " - ", " v "]
    p_local, p_visita = None, None
    
    for sep in separadores:
        if sep in partido_pick.lower():
            partes = re.split(re.escape(sep), partido_pick, flags=re.IGNORECASE)
            if len(partes) == 2:
                p_local, p_visita = partes[0].strip(), partes[1].strip()
                break
                
    if not p_local or not p_visita:
        return False

    # 2. Obtener tokens
    set_p_local = normalizar_nombre_equipo_v2(p_local)
    set_p_visita = normalizar_nombre_equipo_v2(p_visita)
    set_a_home = normalizar_nombre_equipo_v2(home_api)
    set_a_away = normalizar_nombre_equipo_v2(away_api)

    if not set_p_local or not set_p_visita or not set_a_home or not set_a_away:
        return False

    # 3. Matching (Directo o Invertido)
    # Exigimos que AMBOS equipos tengan al menos un token coincidente
    match_normal = (set_p_local & set_a_home) and (set_p_visita & set_a_away)
    match_invertido = (set_p_local & set_a_away) and (set_p_visita & set_a_home)

    if not (match_normal or match_invertido):
        return False

    # 4. Control de Ambigüedad (Seguridad Crítica)
    # Si un equipo del pick coincide con AMBOS equipos de la API, hay colisión (ej: Manchester United vs Manchester City)
    # En ese caso, exigimos que la intersección sea desigual para desempatar
    if match_normal:
        # El local del pick no debe ser "más parecido" al visitante de la API que al local de la API
        if (set_p_local & set_a_away) and len(set_p_local & set_a_away) >= len(set_p_local & set_a_home):
            return False
            
    return True
    """Carga el prompt de automatización."""
    base_dir = Path(__file__).resolve().parent.parent
    rutas_candidatas = [
        base_dir / "01_PROMPTS" / "automatizacion" / "analista_prompt_automatico.txt",
        base_dir / "01_PROMPTS" / "analista_prompt_automatico.txt",
        base_dir / "prompts" / "analista_prompt_automatico.txt",
    ]
    for ruta_prompt in rutas_candidatas:
        if ruta_prompt.exists():
            with open(ruta_prompt, "r", encoding="utf-8") as archivo:
                contenido = archivo.read().strip()
                if contenido:
                    return contenido
    return PROMPT_AUTOMATICO_FALLBACK


COMPARATIVA_PATH = Path(__file__).resolve().parent / "data" / "comparativa_espejo.json"


def cargar_comparativas():
    """Carga las comparativas guardadas."""
    if not COMPARATIVA_PATH.exists():
        return []
    try:
        import json
        with open(COMPARATIVA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def guardar_comparativas(registros):
    """Guarda las comparativas."""
    import json
    COMPARATIVA_PATH.parent.mkdir(exist_ok=True)
    with open(COMPARATIVA_PATH, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)
