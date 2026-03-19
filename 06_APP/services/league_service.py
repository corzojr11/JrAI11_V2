import json
import os
import unicodedata

LEAGUE_MAPPING_FILE = os.path.join(os.path.dirname(__file__), '..', 'config', 'league_mapping.json')

# ============================================
# NOMBRES LEGIBLES DE LIGAS
# ============================================
LIGAS_NOMBRES = {
    "soccer_colombia_primera_a":           "🇨🇴 Liga BetPlay (Colombia)",
    "soccer_colombia_primera_b":           "🇨🇴 Primera B (Colombia)",
    "soccer_uefa_champions_league":        "🏆 UEFA Champions League",
    "soccer_uefa_europa_league":           "🏆 UEFA Europa League",
    "soccer_uefa_conference_league":       "🏆 UEFA Conference League",
    "soccer_conmebol_libertadores":        "🏆 Copa Libertadores",
    "soccer_conmebol_sudamericana":        "🏆 Copa Sudamericana",
    "soccer_fifa_world_cup":               "🌍 FIFA World Cup",
    "soccer_conmebol_world_cup_qualifying":"🌎 Eliminatorias Sudamericanas",
    "soccer_epl":                          "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
    "soccer_england_championship":         "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship",
    "soccer_england_league1":              "🏴󠁧󠁢󠁥󠁮󠁧󠁿 League One",
    "soccer_england_league2":              "🏴󠁧󠁢󠁥󠁮󠁧󠁿 League Two",
    "soccer_spain_la_liga":                "🇪🇸 La Liga",
    "soccer_spain_segunda_division":       "🇪🇸 La Liga 2",
    "soccer_italy_serie_a":                "🇮🇹 Serie A",
    "soccer_italy_serie_b":                "🇮🇹 Serie B",
    "soccer_germany_bundesliga":           "🇩🇪 Bundesliga",
    "soccer_germany_bundesliga_2":         "🇩🇪 2. Bundesliga",
    "soccer_france_ligue_one":             "🇫🇷 Ligue 1",
    "soccer_france_ligue_two":             "🇫🇷 Ligue 2",
    "soccer_brazil_serie_a":               "🇧🇷 Brasileirao Serie A",
    "soccer_brazil_serie_b":               "🇧🇷 Brasileirao Serie B",
    "soccer_argentina_primera_division":   "🇦🇷 Liga Profesional Argentina",
    "soccer_usa_mls":                      "🇺🇸 MLS",
    "soccer_mexico_ligamx":                "🇲🇽 Liga MX",
    "soccer_portugal_primeira_liga":       "🇵🇹 Primeira Liga",
    "soccer_netherlands_eredivisie":       "🇳🇱 Eredivisie",
    "soccer_belgium_first_div":            "🇧🇪 Jupiler Pro League",
    "soccer_turkey_super_lig":             "🇹🇷 Süper Lig",
    "soccer_greece_super_league":          "🇬🇷 Super League Greece",
    "soccer_chile_primera_division":       "🇨🇱 Primera División Chile",
    "soccer_peru_primera_division":        "🇵🇪 Liga 1 Perú",
    "soccer_ecuador_primera_a":            "🇪🇨 Liga Pro Ecuador",
    "soccer_venezuela_primera":            "🇻🇪 Liga Venezolana",
    "soccer_uruguay_primera":              "🇺🇾 Primera División Uruguay",
    "soccer_japan_j_league":               "🇯🇵 J1 League",
    "soccer_south_korea_kleague1":         "🇰🇷 K League 1",
    "soccer_saudi_professional_league":    "🇸🇦 Saudi Pro League",
}

# ============================================
# EQUIPOS POR LIGA (para detección automática)
# ============================================
EQUIPOS_POR_LIGA = {
    "soccer_colombia_primera_a": [
        "atletico nacional", "nacional", "deportes tolima", "tolima",
        "millonarios", "america de cali", "america", "deportivo cali", "cali",
        "independiente medellin", "medellin", "once caldas", "junior",
        "atletico bucaramanga", "bucaramanga", "deportivo pereira", "pereira",
        "envigado", "aguilas doradas", "aguilas", "santa fe", "alianza petrolera",
        "jaguares", "boyaca chico", "chico", "cucuta", "fortaleza",
        "rionegro", "deportivo pasto", "pasto", "patriotas", "llaneros",
        "uniagraria", "uniautonoma",
    ],
    "soccer_epl": [
        "manchester united", "manchester city", "liverpool", "chelsea", "arsenal",
        "tottenham", "leicester", "everton", "west ham", "wolverhampton",
        "wolves", "aston villa", "newcastle", "leeds", "southampton",
        "brighton", "crystal palace", "burnley", "watford", "norwich",
        "brentford", "fulham", "nottingham forest", "bournemouth", "luton",
        "sheffield united", "ipswich", "west brom",
    ],
    "soccer_spain_la_liga": [
        "real madrid", "barcelona", "atletico madrid", "sevilla", "valencia",
        "villarreal", "betis", "real sociedad", "athletic bilbao", "athletic club",
        "espanyol", "getafe", "granada", "osasuna", "celta vigo", "celta",
        "alaves", "levante", "cadiz", "mallorca", "rayo vallecano", "rayo",
        "girona", "las palmas", "leganes", "valladolid",
    ],
    "soccer_italy_serie_a": [
        "juventus", "milan", "inter", "roma", "lazio", "napoli", "atalanta",
        "fiorentina", "torino", "sassuolo", "udinese", "sampdoria", "genoa",
        "cagliari", "bologna", "verona", "empoli", "spezia", "venezia",
        "salernitana", "monza", "lecce", "frosinone", "como",
    ],
    "soccer_germany_bundesliga": [
        "bayern munich", "borussia dortmund", "dortmund", "rb leipzig", "leipzig",
        "bayer leverkusen", "leverkusen", "wolfsburg", "eintracht frankfurt",
        "frankfurt", "borussia monchengladbach", "gladbach", "union berlin",
        "freiburg", "hoffenheim", "mainz", "augsburg", "stuttgart",
        "hertha berlin", "hertha", "bochum", "schalke", "werder bremen", "bremen",
        "hamburgo", "dusseldorf", "heidenheim", "darmstadt", "st. pauli",
    ],
    "soccer_france_ligue_one": [
        "psg", "paris saint germain", "paris saint-germain", "marseille",
        "monaco", "lyon", "lille", "rennes", "nice", "strasbourg",
        "montpellier", "nantes", "brest", "lens", "reims", "angers",
        "clermont", "troyes", "lorient", "metz", "bordeaux", "saint-etienne",
        "toulouse", "le havre", "auxerre",
    ],
    "soccer_brazil_serie_a": [
        "flamengo", "palmeiras", "atletico mineiro", "atletico-mg", "fluminense",
        "sao paulo", "corinthians", "santos", "botafogo", "vasco",
        "internacional", "gremio", "cruzeiro", "bahia", "fortaleza",
        "atletico goianiense", "goias", "cuiaba", "coritiba", "america-mg",
        "bragantino", "athletico paranaense", "athletico-pr",
    ],
    "soccer_argentina_primera_division": [
        "boca juniors", "boca", "river plate", "river", "racing club", "racing",
        "independiente", "san lorenzo", "estudiantes", "lanus", "velez",
        "huracan", "defensa y justicia", "defensa", "talleres", "newells",
        "rosario central", "central", "gimnasia", "banfield", "belgrano",
        "tigre", "platense", "sarmiento", "atletico tucuman", "tucuman",
    ],
    "soccer_usa_mls": [
        "la galaxy", "galaxy", "lafc", "los angeles fc", "seattle sounders",
        "seattle", "portland timbers", "portland", "atlanta united", "atlanta",
        "new york city", "nycfc", "new york red bulls", "red bulls",
        "inter miami", "miami", "chicago fire", "chicago", "toronto fc",
        "toronto", "montreal", "cf montreal", "columbus crew", "columbus",
        "sporting kc", "sporting kansas city", "houston dynamo", "houston",
        "real salt lake", "colorado rapids", "colorado", "minnesota united",
        "minnesota", "fc dallas", "dallas", "vancouver whitecaps", "vancouver",
    ],
    "soccer_mexico_ligamx": [
        "chivas", "guadalajara", "america", "club america", "cruz azul",
        "pumas", "unam", "tigres", "monterrey", "toluca", "santos laguna",
        "santos", "leon", "atlas", "pachuca", "queretaro", "necaxa",
        "puebla", "tijuana", "xolos", "mazatlan", "juarez", "atletico san luis",
    ],
    "soccer_portugal_primeira_liga": [
        "benfica", "porto", "sporting cp", "sporting", "braga", "vitoria guimaraes",
        "vitoria", "rio ave", "moreirense", "pacos ferreira", "famalicao",
        "maritimo", "santa clara", "gil vicente", "estoril",
    ],
    "soccer_netherlands_eredivisie": [
        "ajax", "psv", "feyenoord", "az alkmaar", "az", "utrecht",
        "vitesse", "twente", "groningen", "heracles", "sparta rotterdam",
        "sparta", "sc heerenveen", "heerenveen", "fortuna sittard",
    ],
    "soccer_turkey_super_lig": [
        "galatasaray", "fenerbahce", "besiktas", "trabzonspor", "istanbul basaksehir",
        "basaksehir", "sivasspor", "alanyaspor", "kayserispor", "antalyaspor",
    ],
    "soccer_saudi_professional_league": [
        "al hilal", "al nassr", "cristiano", "al ittihad", "ittihad",
        "al ahli", "al qadsiah", "al shabab", "al fateh", "al wehda",
    ],
    "soccer_chile_primera_division": [
        "colo colo", "universidad de chile", "la u", "universidad catolica",
        "catolica", "palestino", "union espanola", "audax italiano",
        "everton", "cobresal", "deportes iquique", "curico unido",
    ],
    "soccer_peru_primera_division": [
        "alianza lima", "alianza", "universitario", "sporting cristal", "cristal",
        "melgar", "cajamarca", "mannucci", "cienciano", "ayacucho",
    ],
    "soccer_ecuador_primera_a": [
        "barcelona sc", "emelec", "liga de quito", "ldu", "independiente del valle",
        "independiente", "aucas", "el nacional", "delfin", "macara",
    ],
    "soccer_uruguay_primera": [
        "nacional", "penarol", "defensor sporting", "danubio", "river plate",
        "fenix", "progreso", "rentistas", "plaza colonia",
    ],
    "soccer_conmebol_libertadores": [
        "flamengo", "palmeiras", "river plate", "boca juniors", "atletico mineiro",
        "nacional", "penarol", "estudiantes", "olimpia", "cerro porteno",
    ],
}

# ============================================
# MAPEO PARA API-FOOTBALL
# ============================================
API_FOOTBALL_LEAGUE_IDS = {
    "soccer_colombia_primera_a":            239,
    "soccer_colombia_primera_b":            240,
    "soccer_uefa_champions_league":         2,
    "soccer_uefa_europa_league":            3,
    "soccer_uefa_conference_league":        848,
    "soccer_conmebol_libertadores":         13,
    "soccer_conmebol_sudamericana":         11,
    "soccer_fifa_world_cup":                1,
    "soccer_conmebol_world_cup_qualifying": 18,
    "soccer_epl":                           39,
    "soccer_england_championship":          40,
    "soccer_england_league1":               41,
    "soccer_england_league2":               42,
    "soccer_spain_la_liga":                 140,
    "soccer_spain_segunda_division":        141,
    "soccer_italy_serie_a":                 135,
    "soccer_italy_serie_b":                 136,
    "soccer_germany_bundesliga":            78,
    "soccer_germany_bundesliga_2":          79,
    "soccer_france_ligue_one":              61,
    "soccer_france_ligue_two":              62,
    "soccer_brazil_serie_a":                71,
    "soccer_brazil_serie_b":                72,
    "soccer_usa_mls":                       253,
    "soccer_mexico_ligamx":                 262,
    "soccer_portugal_primeira_liga":        94,
    "soccer_netherlands_eredivisie":        88,
    "soccer_belgium_first_div":             144,
    "soccer_turkey_super_lig":              203,
    "soccer_greece_super_league":           197,
    "soccer_argentina_primera_division":    128,
    "soccer_chile_primera_division":        265,
    "soccer_peru_primera_division":         268,
    "soccer_ecuador_primera_a":             266,
    "soccer_uruguay_primera":               278,
    "soccer_saudi_professional_league":     307,
    "soccer_japan_j_league":                98,
    "soccer_south_korea_kleague1":          292,
}

# ============================================
# FUNCIONES
# ============================================
def normalizar(texto):
    """Convierte a minúsculas y elimina tildes para matching robusto."""
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto

def detectar_liga_automatica(nombre_partido):
    """
    Detecta la liga automáticamente buscando equipos en el nombre del partido.
    Retorna (liga_key, nombre_liga) o (None, None) si no detecta.
    """
    partido_norm = normalizar(nombre_partido)
    for liga_key, equipos in EQUIPOS_POR_LIGA.items():
        for equipo in equipos:
            equipo_norm = normalizar(equipo)
            if equipo_norm in partido_norm:
                nombre_liga = LIGAS_NOMBRES.get(liga_key, liga_key)
                return liga_key, nombre_liga
    return None, None

def load_league_mapping():
    """Carga el mapeo legacy desde JSON (compatibilidad hacia atrás)."""
    try:
        with open(LEAGUE_MAPPING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def get_league_key(partido):
    """
    Detecta la liga del partido. Primero intenta detección automática,
    luego cae al mapeo legacy del JSON.
    Compatibilidad hacia atrás garantizada.
    """
    liga_key, _ = detectar_liga_automatica(partido)
    if liga_key:
        return liga_key
    # Fallback al mapeo legacy
    mapping = load_league_mapping()
    for equipo, liga in mapping.items():
        if equipo.lower() in partido.lower():
            return liga
    return None

def get_nombre_liga(liga_key):
    """Retorna el nombre legible de una liga."""
    return LIGAS_NOMBRES.get(liga_key, liga_key)

def get_todas_las_ligas():
    """Retorna lista de (liga_key, nombre_legible) para selectores."""
    return [(k, v) for k, v in LIGAS_NOMBRES.items()]

def get_api_football_league_id(league_key):
    """Retorna el ID de liga para API-Football."""
    return API_FOOTBALL_LEAGUE_IDS.get(league_key)