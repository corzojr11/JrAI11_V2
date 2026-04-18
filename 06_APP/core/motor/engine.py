import math


_EMPIRICAL_PROFILE_CACHE = {"rows": None}


def _to_float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(str(value).replace("%", "").replace(",", ".").strip())
    except Exception:
        return default


def _safe_div(a, b, default=0.0):
    try:
        if not b:
            return default
        return a / b
    except Exception:
        return default


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _poisson_pmf(k, lam):
    if lam is None or lam < 0:
        return 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _score_matrix(lambda_local, lambda_visitante, max_goals=10):
    matrix = []
    for i in range(max_goals + 1):
        row = []
        for j in range(max_goals + 1):
            row.append(_poisson_pmf(i, lambda_local) * _poisson_pmf(j, lambda_visitante))
        matrix.append(row)
    return matrix


def _matrix_market_probs(matrix):
    p_local = 0.0
    p_empate = 0.0
    p_visitante = 0.0
    p_over25 = 0.0
    p_btts = 0.0
    for i, row in enumerate(matrix):
        for j, prob in enumerate(row):
            if i > j:
                p_local += prob
            elif i == j:
                p_empate += prob
            else:
                p_visitante += prob
            if (i + j) >= 3:
                p_over25 += prob
            if i > 0 and j > 0:
                p_btts += prob
    return {
        "p_local": _clamp(p_local),
        "p_empate": _clamp(p_empate),
        "p_visitante": _clamp(p_visitante),
        "p_over25": _clamp(p_over25),
        "p_under25": _clamp(1 - p_over25),
        "p_btts": _clamp(p_btts),
        "p_no_btts": _clamp(1 - p_btts),
    }


def _dixon_coles_adjustment(i, j, lambda_local, lambda_visitante, rho):
    if i == 0 and j == 0:
        return 1 - (lambda_local * lambda_visitante * rho)
    if i == 0 and j == 1:
        return 1 + (lambda_local * rho)
    if i == 1 and j == 0:
        return 1 + (lambda_visitante * rho)
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def _dixon_coles_matrix(lambda_local, lambda_visitante, rho=-0.13, max_goals=10):
    base = _score_matrix(lambda_local, lambda_visitante, max_goals=max_goals)
    adjusted = []
    total = 0.0
    for i, row in enumerate(base):
        new_row = []
        for j, prob in enumerate(row):
            adj = max(0.0, prob * _dixon_coles_adjustment(i, j, lambda_local, lambda_visitante, rho))
            new_row.append(adj)
            total += adj
        adjusted.append(new_row)
    if total > 0:
        adjusted = [[prob / total for prob in row] for row in adjusted]
    return adjusted


def _resultado_desde_marcador(marcador):
    try:
        a, b = str(marcador).split("-")
        goles_a = int(a.strip())
        goles_b = int(b.strip())
        if goles_a > goles_b:
            return 3
        if goles_a == goles_b:
            return 1
        return 0
    except Exception:
        return None


def _forma_ponderada(resultados):
    pesos = [5, 4, 3, 2, 1]
    puntos = 0.0
    pesos_usados = 0.0
    for idx, item in enumerate((resultados or [])[:5]):
        res = _resultado_desde_marcador(item.get("marcador", ""))
        if res is None:
            continue
        peso = pesos[idx]
        puntos += res * peso
        pesos_usados += peso
    indice = _safe_div(puntos, pesos_usados, 0.0)
    return round(indice, 2)


def _lambda_base(home, away, league_stats=None):
    # Promedios globales de referencia si no hay datos de liga
    avg_h = 1.45
    avg_a = 1.15
    if league_stats:
        avg_h = _to_float(league_stats.get("avg_home_goals"), 1.45)
        avg_a = _to_float(league_stats.get("avg_away_goals"), 1.15)
        
    gf_local = _to_float(home.get("goles_favor"), avg_h)
    gc_local = _to_float(home.get("goles_contra"), avg_a)
    gf_visit = _to_float(away.get("goles_favor"), avg_a)
    gc_visit = _to_float(away.get("goles_contra"), avg_h)
    
    # Attack Strength = Goles a favor / Promedio
    att_h = _safe_div(gf_local, avg_h, 1.0)
    att_a = _safe_div(gf_visit, avg_a, 1.0)
    
    # Defense Strength = Goles en contra / Promedio
    def_h = _safe_div(gc_local, avg_a, 1.0)
    def_a = _safe_div(gc_visit, avg_h, 1.0)
    
    lambda_local = att_h * def_a * avg_h
    lambda_visitante = att_a * def_h * avg_a
    
    return round(lambda_local, 3), round(lambda_visitante, 3)


def _elo_probability(elo_local, elo_visitante):
    if elo_local is None or elo_visitante is None:
        return None
    diferencia = (elo_local - elo_visitante) + 100
    prob = 1 / (1 + 10 ** (-diferencia / 400))
    return _clamp(prob)


def _xg_adjustment(gf_real, xg_value):
    if gf_real is None or xg_value is None:
        return None
    sobrerendimiento = gf_real - xg_value
    if sobrerendimiento > 3:
        ajuste = -0.07
    elif sobrerendimiento < -3:
        ajuste = 0.07
    else:
        ajuste = 0.0
    return {"sobrerendimiento": round(sobrerendimiento, 2), "ajuste": ajuste}


def _find_odds_market(odds_data, market_key, bookmaker_preference=None):
    resumen = (odds_data or {}).get("resumen", {})
    options = resumen.get(market_key, [])
    if not options:
        return None
    if bookmaker_preference:
        for item in options:
            if str(item.get("bookmaker", "")).lower() == bookmaker_preference.lower():
                return item
    return options[0]


def _extract_1x2_odds(odds_data):
    market = _find_odds_market(odds_data, "1X2")
    if not market:
        return {}
    values = {}
    for item in market.get("valores", []):
        label = str(item.get("value", "")).strip().lower()
        odd = _to_float(item.get("odd"))
        if odd is None:
            continue
        if label == "home":
            values["local"] = odd
        elif label == "draw":
            values["empate"] = odd
        elif label == "away":
            values["visitante"] = odd
    return values


def _extract_totals_odds(odds_data, line="2.5"):
    market = _find_odds_market(odds_data, "Over/Under")
    if not market:
        return {}
    values = {}
    for item in market.get("valores", []):
        label = str(item.get("value", "")).strip().lower()
        odd = _to_float(item.get("odd"))
        if odd is None:
            continue
        if f"over {line}" in label:
            values["over"] = odd
        elif f"under {line}" in label:
            values["under"] = odd
    return values


def _extract_corners_odds(odds_data, line="9.5"):
    market = _find_odds_market(odds_data, "Corners")
    if not market:
        market = _find_odds_market(odds_data, "Corners Over/Under")
    if not market:
        return {}
    values = {}
    for item in market.get("valores", []):
        label = str(item.get("value", "")).strip().lower()
        odd = _to_float(item.get("odd"))
        if odd is None:
            continue
        if f"over {line}" in label or f"más de {line}" in label:
            values["over"] = odd
        elif f"under {line}" in label or f"menos de {line}" in label:
            values["under"] = odd
    return values


def _extract_btts_odds(odds_data):
    market = _find_odds_market(odds_data, "BTTS")
    if not market:
        return {}
    values = {}
    for item in market.get("valores", []):
        label = str(item.get("value", "")).strip().lower()
        odd = _to_float(item.get("odd"))
        if odd is None:
            continue
        if label == "yes":
            values["si"] = odd
        elif label == "no":
            values["no"] = odd
    return values


def _extract_handicap_reference(odds_data):
    market = _find_odds_market(odds_data, "Handicap")
    if not market:
        return None
    candidates = []
    for item in market.get("valores", []):
        label = str(item.get("value", "")).strip()
        odd = _to_float(item.get("odd"))
        if odd is None:
            continue
        candidates.append({"value": label, "odd": odd})
    return {"bookmaker": market.get("bookmaker", ""), "values": candidates}


def _implied_probability(odd, margin=0.02):
    if odd is None or odd <= 1:
        return None
    base = 1 / odd
    return _clamp(base * (1 - margin))


def _market_verdict(prob_model, prob_market, threshold=0.03):
    if prob_model is None or prob_market is None:
        return "no_disponible"
    if prob_model > prob_market + threshold:
        return "apoya"
    if prob_model + threshold < prob_market:
        return "no_apoya"
    return "neutral"


def _pick_verdict(prob, market_prob):
    if prob is None or market_prob is None:
        return "neutral"
    if prob > market_prob + 0.03:
        return "apoya"
    if prob + 0.03 < market_prob:
        return "no_apoya"
    return "neutral"


def _build_candidates(base_probs, odds_data):
    odds_1x2 = _extract_1x2_odds(odds_data)
    odds_totals = _extract_totals_odds(odds_data)
    odds_btts = _extract_btts_odds(odds_data)
    odds_corners = _extract_corners_odds(odds_data, line="9.5")
    candidates = []

    market_map = [
        ("1X2", "Local", "local", base_probs.get("p_local"), odds_1x2.get("local")),
        ("1X2", "Empate", "empate", base_probs.get("p_empate"), odds_1x2.get("empate")),
        ("1X2", "Visitante", "visitante", base_probs.get("p_visitante"), odds_1x2.get("visitante")),
        ("Over/Under", "Over 2.5", "over25", base_probs.get("p_over25"), odds_totals.get("over")),
        ("Over/Under", "Under 2.5", "under25", base_probs.get("p_under25"), odds_totals.get("under")),
        ("BTTS", "BTTS Si", "btts_si", base_probs.get("p_btts"), odds_btts.get("si")),
        ("BTTS", "BTTS No", "btts_no", base_probs.get("p_no_btts"), odds_btts.get("no")),
        ("Corners", "Over 9.5 Corners", "over95_corners", base_probs.get("p_over95_corners"), odds_corners.get("over")),
        ("Corners", "Under 9.5 Corners", "under95_corners", base_probs.get("p_under95_corners"), odds_corners.get("under")),
    ]
    for mercado, seleccion, key, prob, odd in market_map:
        if prob is None or odd is None:
            continue
        prob_imp = _implied_probability(odd)
        ev = (prob * odd) - 1
        candidates.append(
            {
                "mercado": mercado,
                "seleccion": seleccion,
                "key": key,
                "prob_modelo": _clamp(prob),
                "prob_implicita": prob_imp,
                "cuota": odd,
                "ev": round(ev, 4),
            }
        )
    candidates.sort(key=lambda x: (x["ev"], x["prob_modelo"]), reverse=True)
    return candidates


def _odds_bucket(odd):
    odd = _to_float(odd)
    if odd is None:
        return "sin_cuota"
    if odd < 1.80:
        return "favorito_fuerte"
    if odd < 2.40:
        return "favorito_medio"
    if odd < 3.20:
        return "parejo"
    if odd < 4.50:
        return "cuota_alta"
    return "longshot"


def _outcome_score(resultado):
    resultado = str(resultado or "").strip().lower()
    if resultado == "ganada":
        return 1.0
    if resultado == "media":
        return 0.5
    if resultado == "perdida":
        return 0.0
    return None


def _load_empirical_rows():
    cached = _EMPIRICAL_PROFILE_CACHE.get("rows")
    if cached is not None:
        return cached
    try:
        from database import get_all_picks

        df = get_all_picks(incluir_alternativas=True)
        if df is None or getattr(df, "empty", True):
            _EMPIRICAL_PROFILE_CACHE["rows"] = []
            return []

        rows = []
        for _, row in df.iterrows():
            if str(row.get("ia", "")) != "Motor-Propio":
                continue
            if str(row.get("tipo_pick", "")) != "principal":
                continue
            resultado = _outcome_score(row.get("resultado"))
            if resultado is None:
                continue
            cuota = _to_float(row.get("cuota"))
            if cuota is None:
                continue
            mercado = str(row.get("mercado", "") or "Sin mercado")
            rows.append(
                {
                    "mercado": mercado,
                    "cuota": cuota,
                    "bucket": _odds_bucket(cuota),
                    "resultado_score": resultado,
                    "prob_imp": _implied_probability(cuota),
                    "ganancia": _to_float(row.get("ganancia"), 0.0) or 0.0,
                    "stake": _to_float(row.get("stake"), 0.0) or 0.0,
                }
            )
        _EMPIRICAL_PROFILE_CACHE["rows"] = rows
        return rows
    except Exception:
        _EMPIRICAL_PROFILE_CACHE["rows"] = []
        return []


def _empirical_market_adjustment(candidate):
    rows = _load_empirical_rows()
    mercado = str(candidate.get("mercado", "") or "Sin mercado")
    bucket = _odds_bucket(candidate.get("cuota"))
    same_bucket = [r for r in rows if r["mercado"] == mercado and r["bucket"] == bucket]
    same_market = [r for r in rows if r["mercado"] == mercado]

    sample = same_bucket if len(same_bucket) >= 6 else same_market
    sample_size = len(sample)
    if sample_size < 6:
        return {
            "empirical_adjustment": 0.0,
            "empirical_edge": None,
            "empirical_roi": None,
            "empirical_sample": sample_size,
            "empirical_scope": "insuficiente",
            "notas": [],
        }

    hit_rate = _safe_div(sum(r["resultado_score"] for r in sample), sample_size, 0.0)
    avg_imp = _safe_div(sum(r["prob_imp"] for r in sample if r["prob_imp"] is not None), sample_size, 0.0)
    total_stake = sum(r["stake"] for r in sample)
    roi = _safe_div(sum(r["ganancia"] for r in sample), total_stake, 0.0) if total_stake else 0.0
    empirical_edge = hit_rate - avg_imp

    adjustment = 0.0
    notas = []
    if empirical_edge < -0.03:
        adjustment -= min(0.08, abs(empirical_edge) * 0.7)
        notas.append("mercado_sobreestima_historicamente")
    elif empirical_edge > 0.04 and sample_size >= 10:
        adjustment += min(0.03, empirical_edge * 0.35)
        notas.append("mercado_responde_bien_historicamente")

    if roi < -0.08 and sample_size >= 8:
        adjustment -= min(0.05, abs(roi) * 0.3)
        notas.append("roi_negativo_historico")
    elif roi > 0.10 and sample_size >= 10:
        adjustment += min(0.02, roi * 0.15)
        notas.append("roi_positivo_historico")

    return {
        "empirical_adjustment": round(adjustment, 4),
        "empirical_edge": round(empirical_edge, 4),
        "empirical_roi": round(roi, 4),
        "empirical_sample": sample_size,
        "empirical_scope": "bucket" if sample is same_bucket else "mercado",
        "notas": notas,
    }


def _market_calibration(candidate, favorite_signal, quality_info):
    prob_model = _to_float(candidate.get("prob_modelo"))
    prob_market = _to_float(candidate.get("prob_implicita"))
    cuota = _to_float(candidate.get("cuota"))
    if prob_model is None or prob_market is None or cuota is None:
        return {
            "prob_calibrada": prob_model,
            "ev_calibrado": candidate.get("ev"),
            "shrink_factor": 0.0,
            "ajuste": 0.0,
            "bucket_cuota": _odds_bucket(cuota),
            "notas": [],
        }

    mercado = str(candidate.get("mercado", ""))
    key = str(candidate.get("key", ""))
    bucket = _odds_bucket(cuota)
    notas = []

    # Base de shrinkage hacia mercado segun eficiencia esperada del mercado.
    if mercado == "1X2":
        shrink = 0.10
    elif mercado == "Over/Under":
        shrink = 0.08
    elif mercado == "BTTS":
        shrink = 0.07
    else:
        shrink = 0.08

    # Cuotas largas necesitan mas prudencia; aqui suele vivir el value falso.
    if bucket == "cuota_alta":
        shrink += 0.06
        notas.append("cuota_alta")
    elif bucket == "longshot":
        shrink += 0.12
        notas.append("longshot")
    elif bucket == "favorito_fuerte":
        shrink += 0.01

    # Castigo extra si vamos contra un favorito estructural claro.
    dominante = str((favorite_signal or {}).get("dominante", "equilibrado"))
    if key == "visitante" and dominante == "local":
        shrink += 0.08 if bucket == "longshot" else 0.04
        notas.append("contra_favorito_estructural")
    elif key == "local" and dominante == "visitante":
        shrink += 0.08 if bucket == "longshot" else 0.04
        notas.append("contra_favorito_estructural")
    elif key == "empate" and bucket in {"cuota_alta", "longshot"}:
        shrink += 0.03
        notas.append("empate_precio_alto")

    # Si la calidad de input es buena, soltamos un poco el shrink.
    quality_score = _to_float((quality_info or {}).get("score"), 0.0) or 0.0
    if quality_score >= 90:
        shrink -= 0.03
        notas.append("input_alta_calidad")
    elif quality_score >= 75:
        shrink -= 0.015

    # No dejar que el ajuste sea ni ingenuo ni paralizante.
    shrink = _clamp(shrink, 0.03, 0.28)
    prob_calibrada = _clamp((prob_model * (1 - shrink)) + (prob_market * shrink))
    empirical_meta = _empirical_market_adjustment(candidate)
    prob_calibrada = _clamp(prob_calibrada + empirical_meta.get("empirical_adjustment", 0.0))
    ev_calibrado = round((prob_calibrada * cuota) - 1, 4)
    ajuste = round(prob_calibrada - prob_model, 4)
    notas.extend(empirical_meta.get("notas", []))

    if ajuste < -0.02:
        notas.append("shrink_fuerte_hacia_mercado")
    elif ajuste < 0:
        notas.append("shrink_suave_hacia_mercado")

    return {
        "prob_calibrada": round(prob_calibrada, 4),
        "ev_calibrado": ev_calibrado,
        "shrink_factor": round(shrink, 4),
        "ajuste": ajuste,
        "bucket_cuota": bucket,
        "notas": notas,
        "empirical_adjustment": empirical_meta.get("empirical_adjustment", 0.0),
        "empirical_edge": empirical_meta.get("empirical_edge"),
        "empirical_roi": empirical_meta.get("empirical_roi"),
        "empirical_sample": empirical_meta.get("empirical_sample", 0),
        "empirical_scope": empirical_meta.get("empirical_scope", "insuficiente"),
    }


def _stake_from_rules(sistemas_favor, confianza, ev):
    if sistemas_favor >= 8 and confianza >= 0.85 and ev > 0.08:
        return "3u"
    if sistemas_favor >= 7 and confianza >= 0.75 and ev > 0.05:
        return "2u"
    if sistemas_favor >= 6 and confianza >= 0.70 and ev > 0.03:
        return "1.5u"
    if sistemas_favor >= 5 and confianza >= 0.65 and ev > 0:
        return "1u"
    if sistemas_favor >= 4 and confianza >= 0.62 and ev > 0.03:
        return "0.5u"
    return "NO BET"


def _availability_label(value):
    if value is None:
        return "faltante"
    if isinstance(value, str) and not value.strip():
        return "faltante"
    if isinstance(value, (list, dict)) and not value:
        return "faltante"
    return "listo"


def _referee_cards_signal(manual_data):
    avg_cards = _to_float(manual_data.get("promedio_tarjetas_arbitro"))
    if avg_cards is None:
        return {
            "disponible": False,
            "promedio": None,
            "perfil": "sin_dato",
            "sesgo_over": 0.0,
            "sesgo_under": 0.0,
            "sesgo_btts_si": 0.0,
            "sesgo_btts_no": 0.0,
            "resumen": "",
        }

    if avg_cards >= 5.2:
        perfil = "tarjetero"
        resumen = "Arbitro muy tarjetero; el partido puede romperse por tension y faltas."
        sesgo_over = 0.05
        sesgo_under = -0.03
        sesgo_btts_si = 0.02
        sesgo_btts_no = -0.01
    elif avg_cards <= 3.0:
        perfil = "permisivo"
        resumen = "Arbitro permisivo; el juego puede tener menos interrupciones."
        sesgo_over = 0.02
        sesgo_under = -0.01
        sesgo_btts_si = 0.01
        sesgo_btts_no = 0.02
    else:
        perfil = "normal"
        resumen = "Arbitro de perfil neutro en tarjetas."
        sesgo_over = 0.0
        sesgo_under = 0.0
        sesgo_btts_si = 0.0
        sesgo_btts_no = 0.0

    return {
        "disponible": True,
        "promedio": round(avg_cards, 2),
        "perfil": perfil,
        "sesgo_over": sesgo_over,
        "sesgo_under": sesgo_under,
        "sesgo_btts_si": sesgo_btts_si,
        "sesgo_btts_no": sesgo_btts_no,
        "resumen": resumen,
    }


def _input_quality_score(home, away, manual_data, odds_data, context_info):
    referee_signal = _referee_cards_signal(manual_data)
    bloques = {
        "goles_base": 18 if all(_availability_label(v) == "listo" for v in [home.get("goles_favor"), away.get("goles_favor"), home.get("goles_contra"), away.get("goles_contra")]) else 0,
        "forma": 14 if all(_availability_label(v) == "listo" for v in [home.get("forma"), away.get("forma")]) else 0,
        "xg": 14 if all(_availability_label(v) == "listo" for v in [manual_data.get("xg_local"), manual_data.get("xg_visitante")]) else 0,
        "elo": 14 if all(_availability_label(v) == "listo" for v in [manual_data.get("elo_local"), manual_data.get("elo_visitante")]) else 0,
        "odds": 16 if (odds_data or {}).get("resumen") else 0,
        "stats_sec": 10 if any(_availability_label(v) == "listo" for v in [home.get("shots_on_goal"), away.get("shots_on_goal"), home.get("corners"), away.get("corners")]) else 0,
        "tabla": 8 if any(_availability_label((side.get("tabla") or {}).get("pos")) == "listo" for side in [home, away]) else 0,
        "contexto": 6 if (_availability_label(manual_data.get("contexto_libre")) == "listo" or context_info.get("confianza_contexto")) else 0,
        "arbitro": 4 if referee_signal.get("disponible") else 0,
    }
    score = sum(bloques.values())
    if score >= 80:
        nivel = "alta"
    elif score >= 60:
        nivel = "media"
    else:
        nivel = "baja"
    return {"score": score, "nivel": nivel, "bloques": bloques, "arbitro": referee_signal}


def _market_specific_score(candidate, home, away, lambda_local, lambda_visitante, referee_signal=None, elo_prob=None, forma_diff=0.0):
    key = candidate["key"]
    score = 0.0
    motivos = []
    referee_signal = referee_signal or {}

    shots_local = _to_float(home.get("shots_on_goal"), 0.0) or 0.0
    shots_visit = _to_float(away.get("shots_on_goal"), 0.0) or 0.0
    corners_local = _to_float(home.get("corners"), 0.0) or 0.0
    corners_visit = _to_float(away.get("corners"), 0.0) or 0.0
    pos_local = _to_float(home.get("possession"), 0.0) or 0.0
    pos_visit = _to_float(away.get("possession"), 0.0) or 0.0

    if key == "local":
        if lambda_local > lambda_visitante + 0.35:
            score += 0.18
            motivos.append("ventaja clara en gol esperado")
        elif lambda_local > lambda_visitante + 0.08:
            score += 0.08
            motivos.append("ligera ventaja en gol esperado")
        if shots_local > shots_visit + 1:
            score += 0.08
            motivos.append("mejor volumen ofensivo local")
        if pos_local > pos_visit + 6:
            score += 0.04
            motivos.append("mayor control del partido")
        if elo_prob is not None and elo_prob >= 0.57:
            score += 0.08
            motivos.append("ELO favorece al local")
        if forma_diff >= 0.25:
            score += 0.06
            motivos.append("forma reciente favorece al local")
    elif key == "visitante":
        if lambda_visitante > lambda_local + 0.20:
            score += 0.16
            motivos.append("visita con mejor produccion esperada")
        elif lambda_visitante > lambda_local + 0.05:
            score += 0.07
            motivos.append("visita con ligera ventaja esperada")
        if shots_visit > shots_local + 1:
            score += 0.08
            motivos.append("visita con mejor volumen ofensivo")
        if elo_prob is not None and elo_prob <= 0.48:
            score += 0.08
            motivos.append("ELO favorece a la visita")
        if forma_diff <= -0.25:
            score += 0.06
            motivos.append("forma reciente favorece a la visita")
    elif key == "over25":
        total_lambda = lambda_local + lambda_visitante
        if total_lambda >= 2.8:
            score += 0.18
            motivos.append("lambda total alta")
        if (shots_local + shots_visit) >= 8:
            score += 0.08
            motivos.append("suficientes tiros a puerta")
        if (corners_local + corners_visit) >= 9:
            score += 0.04
            motivos.append("ritmo ofensivo aceptable")
        if referee_signal.get("sesgo_over", 0) > 0:
            score += referee_signal["sesgo_over"]
            motivos.append(f"perfil arbitral {referee_signal.get('perfil')}")
    elif key == "under25":
        total_lambda = lambda_local + lambda_visitante
        if total_lambda <= 2.15:
            score += 0.18
            motivos.append("lambda total contenida")
        if (shots_local + shots_visit) <= 6 and (shots_local + shots_visit) > 0:
            score += 0.08
            motivos.append("poco volumen de remate")
        if referee_signal.get("sesgo_under", 0) > 0:
            score += referee_signal["sesgo_under"]
            motivos.append(f"perfil arbitral {referee_signal.get('perfil')}")
    elif key == "btts_si":
        if lambda_local >= 1.15 and lambda_visitante >= 0.95:
            score += 0.15
            motivos.append("ambos equipos tienen ruta de gol")
        if shots_local >= 3 and shots_visit >= 3:
            score += 0.08
            motivos.append("ambos generan remate al arco")
        if referee_signal.get("sesgo_btts_si", 0) > 0:
            score += referee_signal["sesgo_btts_si"]
            motivos.append(f"perfil arbitral {referee_signal.get('perfil')}")
    elif key == "btts_no":
        if lambda_local < 1.0 or lambda_visitante < 0.8:
            score += 0.14
            motivos.append("uno de los dos equipos proyecta poco gol")
        if min(shots_local, shots_visit) <= 2:
            score += 0.06
            motivos.append("un lado llega con poco volumen")
        if referee_signal.get("sesgo_btts_no", 0) > 0:
            score += referee_signal["sesgo_btts_no"]
            motivos.append(f"perfil arbitral {referee_signal.get('perfil')}")

    return round(score, 4), motivos


def _favorite_structure_signal(poisson_probs, elo_prob, forma_diff):
    score_local = 0.0
    score_visit = 0.0

    if poisson_probs.get("p_local", 0) >= 0.48:
        score_local += 1.0
    if poisson_probs.get("p_local", 0) >= 0.55:
        score_local += 0.6
    if poisson_probs.get("p_visitante", 0) >= 0.34:
        score_visit += 1.0
    if poisson_probs.get("p_visitante", 0) >= 0.40:
        score_visit += 0.6

    if elo_prob is not None:
        if elo_prob >= 0.64:
            score_local += 1.3
        elif elo_prob >= 0.57:
            score_local += 0.8
        if elo_prob <= 0.43:
            score_visit += 0.8
        if elo_prob <= 0.36:
            score_visit += 1.3

    if forma_diff >= 0.45:
        score_local += 0.8
    elif forma_diff >= 0.25:
        score_local += 0.4
    if forma_diff <= -0.45:
        score_visit += 0.8
    elif forma_diff <= -0.25:
        score_visit += 0.4

    if score_local >= score_visit + 1.2:
        dominante = "local"
    elif score_visit >= score_local + 1.2:
        dominante = "visitante"
    else:
        dominante = "parejo"

    return {
        "dominante": dominante,
        "score_local": round(score_local, 2),
        "score_visitante": round(score_visit, 2),
    }


def _candidate_guardrails(candidate, favorite_signal, elo_prob, forma_diff):
    penalizacion = 0.0
    alertas = []
    key = candidate.get("key")
    cuota = candidate.get("cuota", 0) or 0
    dominante = favorite_signal.get("dominante", "parejo")

    if key == "visitante" and dominante == "local":
        penalizacion += 0.42
        alertas.append("underdog visitante contra favorito estructural local")
        if cuota >= 4.5:
            penalizacion += 0.22
            alertas.append("cuota larga visitante sin soporte suficiente")
        if elo_prob is not None and elo_prob >= 0.68:
            penalizacion += 0.15
            alertas.append("ELO favorece con claridad al local")
        if forma_diff >= 0.35:
            penalizacion += 0.08
            alertas.append("forma reciente favorece al local")

    if key == "local" and dominante == "visitante":
        penalizacion += 0.35
        alertas.append("local propuesto contra favorito estructural visitante")
        if cuota >= 4.0:
            penalizacion += 0.12
            alertas.append("cuota larga local sin soporte suficiente")

    if key in ("local", "visitante") and cuota >= 3.8 and candidate.get("market_fit_score", 0) < 0.16:
        penalizacion += 0.14
        alertas.append("moneyline largo con fit de mercado bajo")

    if key == "empate" and cuota >= 3.5 and candidate.get("market_fit_score", 0) < 0.05:
        penalizacion += 0.06
        alertas.append("empate sin soporte estructural claro")

    if key in ("over25", "under25", "btts_si", "btts_no") and dominante != "parejo":
        penalizacion -= 0.03

    return round(max(0.0, penalizacion), 4), alertas


def _build_input_snapshot(home, away, manual_data, odds_data, context_info):
    return {
        "datos_base": {
            "goles_local": _availability_label(home.get("goles_favor")),
            "goles_visitante": _availability_label(away.get("goles_favor")),
            "goles_recibidos_local": _availability_label(home.get("goles_contra")),
            "goles_recibidos_visitante": _availability_label(away.get("goles_contra")),
            "forma_local": _availability_label(home.get("forma")),
            "forma_visitante": _availability_label(away.get("forma")),
            "odds": "listo" if (odds_data or {}).get("resumen") else "faltante",
        },
        "manuales": {
            "xg_local": _availability_label(manual_data.get("xg_local")),
            "xg_visitante": _availability_label(manual_data.get("xg_visitante")),
            "elo_local": _availability_label(manual_data.get("elo_local")),
            "elo_visitante": _availability_label(manual_data.get("elo_visitante")),
            "promedio_tarjetas_arbitro": _availability_label(manual_data.get("promedio_tarjetas_arbitro")),
            "contexto_libre": _availability_label(manual_data.get("contexto_libre")),
            "contexto_estructurado": "listo" if manual_data.get("contexto_ollama") else ("listo" if context_info.get("confianza_contexto") else "faltante"),
        },
    }


def _build_reasoning_summary(best_candidate, sistemas_a_favor, sistemas_total, confidence, prob_final, ev, context_info, quality_info, referee_signal):
    if not best_candidate:
        return {
            "decision": "NO BET",
            "motivos_clave": ["No hubo un mercado candidato con datos suficientes para evaluar valor real."],
            "bloqueos": ["Sin candidato operativo"],
        }

    motivos = [
        f"Mercado lider: {best_candidate['mercado']} / {best_candidate['seleccion']}",
        f"Probabilidad del modelo {prob_final:.1%} frente a implicita {best_candidate['prob_implicita']:.1%}",
        f"{sistemas_a_favor}/{sistemas_total} sistemas apoyan la idea",
    ]
    if ev > 0:
        motivos.append(f"EV estimado de {ev:.1%}")
    if context_info.get("resumen"):
        motivos.append(f"Contexto: {context_info['resumen']}")
    if referee_signal.get("disponible") and referee_signal.get("resumen"):
        motivos.append(f"Arbitro: {referee_signal['resumen']}")
    if best_candidate and best_candidate.get("market_fit_reasons"):
        motivos.append("Perfil mercado: " + ", ".join(best_candidate.get("market_fit_reasons", [])[:3]))

    bloqueos = []
    if ev <= 0:
        bloqueos.append("EV no positivo")
    if confidence < 0.62:
        bloqueos.append("confianza por debajo del umbral")
    soporte_msg = "menos de 5 sistemas a favor"
    if (
        quality_info.get("score", 0) >= 85
        and confidence >= 0.62
        and best_candidate.get("market_fit_score", 0) >= 0.18
        and best_candidate.get("guardrail_penalty", 0) < 0.12
        and ev > 0.03
    ):
        soporte_msg = "menos de 4 sistemas a favor"
    if (soporte_msg == "menos de 5 sistemas a favor" and sistemas_a_favor < 5) or (soporte_msg == "menos de 4 sistemas a favor" and sistemas_a_favor < 4):
        bloqueos.append(soporte_msg)
    if quality_info.get("score", 0) < 55:
        bloqueos.append("calidad de input insuficiente")
    if best_candidate and best_candidate.get("market_fit_score", 0) < 0.08:
        bloqueos.append("mercado sin confirmacion especifica suficiente")

    return {
        "decision": "PICK" if (
            ev > 0
            and confidence >= 0.62
            and (
                sistemas_a_favor >= 5
                or (
                    sistemas_a_favor >= 4
                    and quality_info.get("score", 0) >= 85
                    and best_candidate.get("market_fit_score", 0) >= 0.18
                    and best_candidate.get("guardrail_penalty", 0) < 0.12
                    and ev > 0.03
                )
            )
        ) else "NO BET",
        "motivos_clave": motivos,
        "bloqueos": bloqueos,
    }


def _context_adjustment(contexto_texto):
    texto = str(contexto_texto or "").lower()
    if not texto.strip():
        return {
            "ajuste_total": 0.0,
            "confianza_contexto": 0.0,
            "resumen": "Sin contexto adicional.",
        }

    ajuste = 0.0
    hits = []

    lesiones_fuertes = ["portero titular", "goleador", "lesion importante", "baja sensible"]
    lesiones_medias = ["lesionado", "suspendido", "baja", "ausencia"]
    motivacion_alta = ["titulo", "descenso", "final", "semifinal", "clasificar", "clasificacion", "derbi"]
    motivacion_baja = ["rotacion", "intrascendente", "ya clasificado", "sin jugarse nada"]

    if any(k in texto for k in lesiones_fuertes):
        ajuste -= 0.06
        hits.append("bajas importantes")
    elif any(k in texto for k in lesiones_medias):
        ajuste -= 0.03
        hits.append("bajas confirmadas")

    if any(k in texto for k in motivacion_alta):
        ajuste += 0.04
        hits.append("motivacion alta")
    elif any(k in texto for k in motivacion_baja):
        ajuste -= 0.03
        hits.append("motivacion baja o rotaciones")

    if "5 amarillas" in texto or "arbitro tarjetero" in texto:
        ajuste += 0.01
        hits.append("arbitro intenso")

    ajuste = max(-0.10, min(0.10, ajuste))
    confianza = min(0.85, 0.35 + (0.12 * len(hits)))
    resumen = ", ".join(hits) if hits else "Contexto libre sin señal fuerte."
    return {
        "ajuste_total": round(ajuste, 4),
        "confianza_contexto": round(confianza, 2) if hits else 0.0,
        "resumen": resumen,
    }


def _candidate_support(candidate, poisson_probs, dc_probs, elo_prob, forma_diff, xg_adj_local, xg_adj_visit, odds_data, home, away, lambda_local, lambda_visitante, referee_signal=None):
    target_key = candidate["key"]
    target_prob = candidate["prob_modelo"]
    target_imp = candidate["prob_implicita"]

    poisson_veredicto = _pick_verdict(target_prob, target_imp)

    dixon_target = None
    if target_key == "local":
        dixon_target = dc_probs["p_local"]
    elif target_key == "empate":
        dixon_target = dc_probs["p_empate"]
    elif target_key == "visitante":
        dixon_target = dc_probs["p_visitante"]
    elif target_key == "over25":
        dixon_target = dc_probs["p_over25"]
    elif target_key == "under25":
        dixon_target = dc_probs["p_under25"]
    elif target_key == "btts_si":
        dixon_target = dc_probs["p_btts"]
    elif target_key == "btts_no":
        dixon_target = dc_probs["p_no_btts"]
    dixon_veredicto = _pick_verdict(dixon_target, target_imp)

    if target_key == "local":
        elo_veredicto = "apoya" if elo_prob is not None and elo_prob > 0.56 else ("no_apoya" if elo_prob is not None else "no_disponible")
        forma_veredicto = "apoya" if forma_diff > 0.35 else ("no_apoya" if forma_diff < -0.15 else "neutral")
    elif target_key == "visitante":
        away_prob = None if elo_prob is None else 1 - elo_prob
        elo_veredicto = "apoya" if away_prob is not None and away_prob > 0.45 else ("no_apoya" if away_prob is not None else "no_disponible")
        forma_veredicto = "apoya" if forma_diff < -0.35 else ("no_apoya" if forma_diff > 0.15 else "neutral")
    else:
        elo_veredicto = "neutral" if elo_prob is not None else "no_disponible"
        forma_veredicto = "neutral"

    if xg_adj_local is None or xg_adj_visit is None:
        xg_veredicto = "no_disponible"
    else:
        total_ajuste = xg_adj_local["ajuste"] - xg_adj_visit["ajuste"]
        if target_key == "local":
            xg_veredicto = "apoya" if total_ajuste > 0.02 else ("no_apoya" if total_ajuste < -0.02 else "neutral")
        elif target_key == "visitante":
            xg_veredicto = "apoya" if total_ajuste < -0.02 else ("no_apoya" if total_ajuste > 0.02 else "neutral")
        else:
            xg_veredicto = "neutral"

    handicap_ref = _extract_handicap_reference(odds_data)
    fair_line = 0.0
    if poisson_probs["p_local"] > 0.60:
        fair_line = -0.5
    elif poisson_probs["p_local"] > 0.50:
        fair_line = -0.25
    elif poisson_probs["p_local"] >= 0.45:
        fair_line = 0.0
    market_line = None
    if handicap_ref and handicap_ref.get("values"):
        for item in handicap_ref["values"]:
            if str(item.get("value", "")).lower().startswith("home"):
                parts = str(item.get("value", "")).split(" ")
                if len(parts) >= 2:
                    market_line = _to_float(parts[1])
                    if market_line is not None:
                        break
    delta_linea = round((market_line - fair_line), 2) if market_line is not None else None
    arbitraje_veredicto = "no_disponible" if delta_linea is None else ("apoya" if delta_linea > 0.25 else "neutral")

    p_pinnacle = None
    mercado_eficiente_veredicto = "no_disponible"
    if candidate:
        p_calculada = candidate["prob_modelo"]
        pinnacle_item = None
        if candidate["mercado"] == "1X2":
            pinnacle_market = _find_odds_market(odds_data, "1X2", bookmaker_preference="Pinnacle")
            if pinnacle_market:
                value_key = {"local": "home", "empate": "draw", "visitante": "away"}.get(target_key)
                for item in pinnacle_market.get("valores", []):
                    if str(item.get("value", "")).strip().lower() == value_key:
                        pinnacle_item = item
                        break
        elif candidate["key"] in ("over25", "under25"):
            pinnacle_market = _find_odds_market(odds_data, "Over/Under", bookmaker_preference="Pinnacle")
            if pinnacle_market:
                wanted = "over 2.5" if candidate["key"] == "over25" else "under 2.5"
                for item in pinnacle_market.get("valores", []):
                    if wanted in str(item.get("value", "")).strip().lower():
                        pinnacle_item = item
                        break
        elif candidate["key"] in ("btts_si", "btts_no"):
            pinnacle_market = _find_odds_market(odds_data, "BTTS", bookmaker_preference="Pinnacle")
            if pinnacle_market:
                wanted = "yes" if candidate["key"] == "btts_si" else "no"
                for item in pinnacle_market.get("valores", []):
                    if str(item.get("value", "")).strip().lower() == wanted:
                        pinnacle_item = item
                        break
        if pinnacle_item:
            p_pinnacle = _implied_probability(_to_float(pinnacle_item.get("odd")), margin=0.02)
            mercado_eficiente_veredicto = _market_verdict(p_calculada, p_pinnacle)

    systems = {
        "poisson": poisson_veredicto,
        "dixon_coles": dixon_veredicto,
        "elo": elo_veredicto,
        "regresion_xg": xg_veredicto,
        "forma_ponderada": forma_veredicto,
        "arbitraje_lineas": arbitraje_veredicto,
        "mercado_eficiente": mercado_eficiente_veredicto,
    }
    apoyos = sum(1 for v in systems.values() if v == "apoya")
    neutrales = sum(1 for v in systems.values() if v == "neutral")
    market_fit_score, market_fit_reasons = _market_specific_score(
        candidate,
        home,
        away,
        lambda_local,
        lambda_visitante,
        referee_signal=referee_signal,
        elo_prob=elo_prob,
        forma_diff=forma_diff,
    )
    return systems, apoyos, neutrales, {
        "dixon_target": dixon_target,
        "fair_line": fair_line,
        "market_line": market_line,
        "delta_linea": delta_linea,
        "p_pinnacle": p_pinnacle,
        "market_fit_score": market_fit_score,
        "market_fit_reasons": market_fit_reasons,
    }


def analizar_partido_motor(datos_partido, manual_data=None):
    manual_data = manual_data or {}
    home = (datos_partido or {}).get("home", {})
    away = (datos_partido or {}).get("away", {})
    odds_data = (datos_partido or {}).get("odds", {})
    league_stats = (datos_partido or {}).get("league_stats", {})

    lambda_local, lambda_visitante = _lambda_base(home, away, league_stats)
    poisson_matrix = _score_matrix(lambda_local, lambda_visitante)
    poisson_probs = _matrix_market_probs(poisson_matrix)

    # Corners Baseline Model (Poisson Sum)
    c_local = _to_float(home.get("corners"), 5.5) or 5.5
    c_visit = _to_float(away.get("corners"), 4.5) or 4.5
    total_c_lambda = c_local + c_visit
    p_under_c = sum(_poisson_pmf(k, total_c_lambda) for k in range(10)) # under 9.5
    poisson_probs["p_over95_corners"] = round(1 - p_under_c, 4)
    poisson_probs["p_under95_corners"] = round(p_under_c, 4)

    dc_matrix = _dixon_coles_matrix(lambda_local, lambda_visitante, rho=-0.13)
    dc_probs = _matrix_market_probs(dc_matrix)

    elo_local = _to_float(manual_data.get("elo_local"))
    elo_visitante = _to_float(manual_data.get("elo_visitante"))
    elo_prob = _elo_probability(elo_local, elo_visitante)

    xg_local = _to_float(manual_data.get("xg_local"))
    xg_visitante = _to_float(manual_data.get("xg_visitante"))
    xg_adj_local = _xg_adjustment(_to_float(home.get("goles_favor")), xg_local)
    xg_adj_visit = _xg_adjustment(_to_float(away.get("goles_favor")), xg_visitante)

    forma_local = _forma_ponderada(home.get("forma", []))
    forma_visitante = _forma_ponderada(away.get("forma", []))
    forma_diff = round(forma_local - forma_visitante, 2)
    context_info = manual_data.get("contexto_ollama") or _context_adjustment(manual_data.get("contexto_libre"))
    referee_signal = _referee_cards_signal(manual_data)
    quality_info = _input_quality_score(home, away, manual_data, odds_data, context_info)
    favorite_signal = _favorite_structure_signal(poisson_probs, elo_prob, forma_diff)

    from core.motor.weights import get_system_weights
    sys_weights = get_system_weights()

    candidates = _build_candidates(poisson_probs, odds_data)
    evaluated_candidates = []
    for candidate in candidates:
        systems_candidate, apoyos, neutrales, meta = _candidate_support(
            candidate, poisson_probs, dc_probs, elo_prob, forma_diff, xg_adj_local, xg_adj_visit, odds_data, home, away, lambda_local, lambda_visitante, referee_signal
        )
        candidate_copy = dict(candidate)
        candidate_copy["prob_modelo_bruto"] = candidate_copy.get("prob_modelo")
        candidate_copy["ev_bruto"] = candidate_copy.get("ev")
        candidate_copy["systems"] = systems_candidate
        candidate_copy["sistemas_a_favor"] = apoyos
        candidate_copy["sistemas_neutrales"] = neutrales
        candidate_copy.update(meta)
        calibration_meta = _market_calibration(candidate_copy, favorite_signal, quality_info)
        candidate_copy.update(calibration_meta)
        guardrail_penalty, guardrail_alerts = _candidate_guardrails(candidate_copy, favorite_signal, elo_prob, forma_diff)
        candidate_copy["guardrail_penalty"] = guardrail_penalty
        candidate_copy["guardrail_alerts"] = guardrail_alerts

        # CALCULO DE PESOS PONDERADOS
        # En vez de (apoyos * 0.09) que da maximo 0.63, sumamos los pesos normalizados
        weighted_support = sum(sys_weights.get(sys, 0.1) for sys, veredicto in systems_candidate.items() if veredicto == "apoya")
        weighted_neutrales = sum(sys_weights.get(sys, 0.1) for sys, veredicto in systems_candidate.items() if veredicto == "neutral")
        
        # Max weighted_support = 1.0 -> lo escalamos a 0.63 (como 7 apoyos * 0.09)
        score_support_term = weighted_support * 0.63
        score_neutral_term = weighted_neutrales * 0.07

        candidate_copy["weighted_support"] = round(weighted_support, 3)
        candidate_copy["score_candidato"] = round(
            (candidate_copy.get("ev_calibrado", candidate_copy["ev"]) * 3.2)
            + (candidate_copy.get("prob_calibrada", candidate_copy["prob_modelo"]) * 0.8)
            + score_support_term
            + (candidate_copy.get("market_fit_score", 0) * 0.75)
            + score_neutral_term,
            4,
        )
        candidate_copy["score_ajustado"] = round(candidate_copy["score_candidato"] - guardrail_penalty, 4)
        evaluated_candidates.append(candidate_copy)


    evaluated_candidates.sort(
        key=lambda x: (
            x["sistemas_a_favor"],
            x["score_ajustado"],
            x.get("ev_calibrado", x["ev"]),
            x.get("prob_calibrada", x["prob_modelo"]),
        ),
        reverse=True,
    )
    best_candidate = evaluated_candidates[0] if evaluated_candidates else None

    target_key = best_candidate["key"] if best_candidate else None
    target_prob = best_candidate.get("prob_calibrada", best_candidate["prob_modelo"]) if best_candidate else None
    target_prob_raw = best_candidate["prob_modelo"] if best_candidate else None
    prob_imp = best_candidate["prob_implicita"] if best_candidate else None
    p_pinnacle = best_candidate.get("p_pinnacle") if best_candidate else None
    dixon_target = best_candidate.get("dixon_target") if best_candidate else None
    ajuste_contextual = context_info["ajuste_total"] if best_candidate else 0.0

    if best_candidate:
        systems_verdicts = best_candidate["systems"]
        poisson_veredicto = systems_verdicts["poisson"]
        dixon_veredicto = systems_verdicts["dixon_coles"]
        elo_veredicto = systems_verdicts["elo"]
        xg_veredicto = systems_verdicts["regresion_xg"]
        forma_veredicto = systems_verdicts["forma_ponderada"]
        arbitraje_veredicto = systems_verdicts["arbitraje_lineas"]
        mercado_eficiente_veredicto = systems_verdicts["mercado_eficiente"]
        fair_line = best_candidate.get("fair_line")
        market_line = best_candidate.get("market_line")
        delta_linea = best_candidate.get("delta_linea")
    else:
        poisson_veredicto = dixon_veredicto = forma_veredicto = "neutral"
        elo_veredicto = xg_veredicto = arbitraje_veredicto = mercado_eficiente_veredicto = "no_disponible"
        fair_line = market_line = delta_linea = None

    sistemas = {
        "poisson": {
            "lambda_local": round(lambda_local, 3),
            "lambda_visitante": round(lambda_visitante, 3),
            "p_over25": round(poisson_probs["p_over25"], 4),
            "p_btts": round(poisson_probs["p_btts"], 4),
            "p_local": round(poisson_probs["p_local"], 4),
            "p_empate": round(poisson_probs["p_empate"], 4),
            "p_visitante": round(poisson_probs["p_visitante"], 4),
            "veredicto": poisson_veredicto,
        },
        "dixon_coles": {
            "p_over25_corregido": round(dc_probs["p_over25"], 4),
            "p_btts_corregido": round(dc_probs["p_btts"], 4),
            "p_local_corregido": round(dc_probs["p_local"], 4),
            "p_empate_corregido": round(dc_probs["p_empate"], 4),
            "p_visitante_corregido": round(dc_probs["p_visitante"], 4),
            "veredicto": dixon_veredicto,
        },
        "elo": {
            "elo_local": elo_local,
            "elo_visitante": elo_visitante,
            "p_victoria_local": round(elo_prob, 4) if elo_prob is not None else None,
            "veredicto": elo_veredicto,
        },
        "regresion_xg": {
            "sobrerendimiento_local": None if xg_adj_local is None else xg_adj_local["sobrerendimiento"],
            "sobrerendimiento_visitante": None if xg_adj_visit is None else xg_adj_visit["sobrerendimiento"],
            "veredicto": xg_veredicto,
        },
        "forma_ponderada": {
            "indice_local": round(forma_local, 2),
            "indice_visitante": round(forma_visitante, 2),
            "diferencia": round(forma_diff, 2),
            "veredicto": forma_veredicto,
        },
        "arbitraje_lineas": {
            "linea_justa": fair_line,
            "linea_mercado": market_line,
            "delta": delta_linea,
            "veredicto": arbitraje_veredicto,
        },
        "mercado_eficiente": {
            "p_calculada": round(target_prob, 4) if target_prob is not None else None,
            "p_pinnacle": round(p_pinnacle, 4) if p_pinnacle is not None else None,
            "diferencia": round((target_prob - p_pinnacle), 4) if target_prob is not None and p_pinnacle is not None else None,
            "veredicto": mercado_eficiente_veredicto,
        },
        "calibracion_mercado": {
            "prob_modelo_bruta": round(target_prob_raw, 4) if target_prob_raw is not None else None,
            "prob_modelo_calibrada": round(target_prob, 4) if target_prob is not None else None,
            "shrink_factor": round(best_candidate.get("shrink_factor", 0), 4) if best_candidate else None,
            "bucket_cuota": best_candidate.get("bucket_cuota") if best_candidate else None,
            "ajuste": round(best_candidate.get("ajuste", 0), 4) if best_candidate else None,
            "empirical_adjustment": round(best_candidate.get("empirical_adjustment", 0), 4) if best_candidate else None,
            "empirical_edge": best_candidate.get("empirical_edge") if best_candidate else None,
            "empirical_roi": best_candidate.get("empirical_roi") if best_candidate else None,
            "empirical_sample": best_candidate.get("empirical_sample") if best_candidate else None,
            "empirical_scope": best_candidate.get("empirical_scope") if best_candidate else None,
            "notas": best_candidate.get("notas", []) if best_candidate else [],
            "veredicto": "apoya" if best_candidate and abs(best_candidate.get("ajuste", 0)) <= 0.02 else "neutral",
        },
        "contexto_reglado": {
            "ajuste_total": context_info["ajuste_total"],
            "confianza_contexto": context_info["confianza_contexto"],
            "resumen": context_info["resumen"],
            "veredicto": "apoya" if context_info["ajuste_total"] > 0.01 else ("no_apoya" if context_info["ajuste_total"] < -0.01 else "neutral"),
        },
        "arbitro_tarjetas": {
            "promedio_tarjetas": referee_signal.get("promedio"),
            "perfil": referee_signal.get("perfil"),
            "resumen": referee_signal.get("resumen"),
            "veredicto": "apoya" if referee_signal.get("disponible") else "no_disponible",
        },
    }

    sistemas_total = len(sistemas)
    sistemas_no_disponibles = sum(1 for data in sistemas.values() if data.get("veredicto") == "no_disponible")
    sistemas_a_favor = sum(1 for data in sistemas.values() if data.get("veredicto") == "apoya")

    pesos = {
        "poisson": 0.30,
        "dixon_coles": 0.25,
        "elo": 0.20,
        "regresion_xg": 0.15,
        "forma_ponderada": 0.10,
    }
    available_weights = {k: v for k, v in pesos.items() if sistemas[k].get("veredicto") != "no_disponible"}
    total_weight = sum(available_weights.values()) or 1.0
    prob_base = 0.0
    contribution_map = {
        "poisson": target_prob,
        "dixon_coles": dixon_target,
        "elo": elo_prob if target_key == "local" else (None if elo_prob is None else (1 - elo_prob if target_key == "visitante" else None)),
        "regresion_xg": None,
        "forma_ponderada": None,
    }
    if xg_adj_local is not None and xg_adj_visit is not None and target_prob is not None:
        contribution_map["regresion_xg"] = _clamp(target_prob + (xg_adj_local["ajuste"] - xg_adj_visit["ajuste"]))
    if target_key in ("local", "visitante") and target_prob is not None:
        forma_boost = _clamp(abs(forma_diff) / 10.0, 0.0, 0.08)
        if target_key == "local":
            contribution_map["forma_ponderada"] = _clamp(target_prob + forma_boost if forma_diff > 0 else target_prob - forma_boost)
        else:
            contribution_map["forma_ponderada"] = _clamp(target_prob + forma_boost if forma_diff < 0 else target_prob - forma_boost)

    for key, weight in available_weights.items():
        contrib = contribution_map.get(key)
        if contrib is not None:
            prob_base += contrib * (weight / total_weight)

    prob_final = _clamp(prob_base + ajuste_contextual)
    ev = best_candidate["ev"] if best_candidate else -1.0
    if best_candidate and best_candidate.get("cuota"):
        ev = round((prob_final * best_candidate["cuota"]) - 1, 4)

    confidence_components = []
    if prob_final:
        confidence_components.append(prob_final)
    confidence_components.append(min(1.0, sistemas_a_favor / max(5, sistemas_total - sistemas_no_disponibles or 1)))
    if context_info["confianza_contexto"]:
        confidence_components.append(context_info["confianza_contexto"] * 0.35)
    if best_candidate:
        confidence_components.append(min(0.18, best_candidate.get("market_fit_score", 0)))
        confidence_components.append(min(0.12, max(0.0, best_candidate.get("ev", 0)) * 0.25))
    confidence = round(sum(confidence_components) / max(1, len(confidence_components)), 2)
    quality_factor = 0.82 if quality_info["nivel"] == "baja" else (0.92 if quality_info["nivel"] == "media" else 1.0)
    confidence = round(_clamp(confidence * quality_factor), 2)

    riesgos = []
    datos_insuficientes = []
    for nombre, data in sistemas.items():
        if data.get("veredicto") == "no_disponible":
            datos_insuficientes.append(nombre)
    if datos_insuficientes:
        riesgos.append("Hay sistemas no disponibles por datos faltantes.")
    if best_candidate and best_candidate.get("ev_calibrado", best_candidate["ev"]) <= 0:
        riesgos.append("El valor esperado no supera 0.")
    if best_candidate and best_candidate.get("ajuste", 0) <= -0.03:
        riesgos.append("La calibracion de mercado recorto bastante la probabilidad; cuidado con edge posiblemente inflado.")
    if confidence < 0.62:
        riesgos.append("La confianza agregada sigue por debajo del umbral operativo.")
    if best_candidate and best_candidate["mercado"] != "1X2" and best_candidate["sistemas_a_favor"] < 5:
        riesgos.append("El mercado secundario no tiene apoyo suficiente.")
    if quality_info["nivel"] == "baja":
        riesgos.append("La calidad del input es baja; el motor penalizo la confianza.")
    elif quality_info["nivel"] == "media":
        riesgos.append("La calidad del input es intermedia; conviene revisar antes de publicar.")
    if not referee_signal.get("disponible"):
        riesgos.append("Falta el promedio de tarjetas del arbitro; se pierde una senal util de tension del partido.")
    if best_candidate and best_candidate.get("market_fit_score", 0) < 0.10:
        riesgos.append("El mercado elegido no tiene suficiente confirmacion especifica por perfil de juego.")
    if best_candidate and best_candidate.get("bucket_cuota") == "longshot" and best_candidate.get("ajuste", 0) < 0:
        riesgos.append("Es una cuota larga y fue castigada por calibracion hacia mercado.")
    if best_candidate and best_candidate.get("guardrail_alerts"):
        riesgos.extend(best_candidate.get("guardrail_alerts", []))

    soporte_minimo = 5
    if (
        best_candidate
        and quality_info["score"] >= 85
        and confidence >= 0.62
        and best_candidate.get("market_fit_score", 0) >= 0.18
        and best_candidate.get("guardrail_penalty", 0) < 0.12
        and ev > 0.03
    ):
        soporte_minimo = 4

    emitido = bool(
        best_candidate
        and sistemas_a_favor >= soporte_minimo
        and confidence >= 0.62
        and ev > 0
        and quality_info["score"] >= 55
        and best_candidate.get("market_fit_score", 0) >= 0.08
        and best_candidate.get("guardrail_penalty", 0) < 0.25
    )
    stake = _stake_from_rules(sistemas_a_favor, confidence, ev)
    if stake == "NO BET":
        emitido = False

    razonamiento = "No hay ventaja suficiente para emitir pick."
    if emitido and best_candidate:
        razonamiento = (
            f"El modelo propio ve valor en {best_candidate['seleccion']} con probabilidad estimada de "
            f"{prob_final:.1%} frente a una implicita de {best_candidate['prob_implicita']:.1%}. "
            f"{sistemas_a_favor}/{sistemas_total} sistemas apoyan la idea."
        )

    snapshot = _build_input_snapshot(home, away, manual_data, odds_data, context_info)
    reasoning_summary = _build_reasoning_summary(
        best_candidate,
        sistemas_a_favor,
        sistemas_total,
        confidence,
        prob_final,
        ev,
        context_info,
        quality_info,
        referee_signal,
    )

    return {
        "partido": datos_partido.get("partido", ""),
        "fecha": datos_partido.get("fecha", ""),
        "candidatos": evaluated_candidates[:5],
        "entrada_utilizada": snapshot,
        "calidad_input": quality_info,
        "favorito_estructural": favorite_signal,
        "sistemas": sistemas,
        "consenso": {
            "sistemas_a_favor": sistemas_a_favor,
            "sistemas_total": sistemas_total,
            "sistemas_no_disponibles": sistemas_no_disponibles,
        },
        "probabilidad_final": {
            "base_ponderada": round(prob_base, 4),
            "ajuste_contextual": round(ajuste_contextual, 4),
            "final": round(prob_final, 4),
        },
        "pick": {
            "emitido": emitido,
            "mercado": "" if not best_candidate else best_candidate["mercado"],
            "seleccion": "" if not best_candidate else best_candidate["seleccion"],
            "cuota": 0.0 if not best_candidate else round(best_candidate["cuota"], 2),
            "probabilidad_estimada": round(prob_final, 4),
            "probabilidad_implicita": round(prob_imp, 4) if prob_imp is not None else 0.0,
            "valor_esperado": round(ev, 4) if best_candidate else -1.0,
            "confianza": confidence,
            "stake_recomendado": stake,
            "razonamiento": razonamiento,
        },
        "decision_motor": reasoning_summary,
        "riesgos": riesgos,
        "datos_insuficientes": datos_insuficientes,
    }
