import math


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


def _lambda_base(home, away):
    gf_local = _to_float(home.get("goles_favor"), 0.0) or 0.0
    gc_local = _to_float(home.get("goles_contra"), 0.0) or 0.0
    gf_visit = _to_float(away.get("goles_favor"), 0.0) or 0.0
    gc_visit = _to_float(away.get("goles_contra"), 0.0) or 0.0
    lambda_local = ((gf_local + gc_visit) / 2.0) * 1.10 if (gf_local or gc_visit) else 0.0
    lambda_visit = ((gf_visit + gc_local) / 2.0) if (gf_visit or gc_local) else 0.0
    return round(lambda_local, 3), round(lambda_visit, 3)


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
    candidates = []

    market_map = [
        ("1X2", "Local", "local", base_probs.get("p_local"), odds_1x2.get("local")),
        ("1X2", "Empate", "empate", base_probs.get("p_empate"), odds_1x2.get("empate")),
        ("1X2", "Visitante", "visitante", base_probs.get("p_visitante"), odds_1x2.get("visitante")),
        ("Over/Under", "Over 2.5", "over25", base_probs.get("p_over25"), odds_totals.get("over")),
        ("Over/Under", "Under 2.5", "under25", base_probs.get("p_under25"), odds_totals.get("under")),
        ("BTTS", "BTTS Si", "btts_si", base_probs.get("p_btts"), odds_btts.get("si")),
        ("BTTS", "BTTS No", "btts_no", base_probs.get("p_no_btts"), odds_btts.get("no")),
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


def _stake_from_rules(sistemas_favor, confianza, ev):
    if sistemas_favor >= 8 and confianza >= 0.85 and ev > 0.08:
        return "3u"
    if sistemas_favor >= 7 and confianza >= 0.75 and ev > 0.05:
        return "2u"
    if sistemas_favor >= 6 and confianza >= 0.70 and ev > 0.03:
        return "1.5u"
    if sistemas_favor >= 5 and confianza >= 0.65 and ev > 0:
        return "1u"
    return "NO BET"


def _availability_label(value):
    if value is None:
        return "faltante"
    if isinstance(value, str) and not value.strip():
        return "faltante"
    if isinstance(value, (list, dict)) and not value:
        return "faltante"
    return "listo"


def _input_quality_score(home, away, manual_data, odds_data, context_info):
    bloques = {
        "goles_base": 18 if all(_availability_label(v) == "listo" for v in [home.get("goles_favor"), away.get("goles_favor"), home.get("goles_contra"), away.get("goles_contra")]) else 0,
        "forma": 14 if all(_availability_label(v) == "listo" for v in [home.get("forma"), away.get("forma")]) else 0,
        "xg": 14 if all(_availability_label(v) == "listo" for v in [manual_data.get("xg_local"), manual_data.get("xg_visitante")]) else 0,
        "elo": 14 if all(_availability_label(v) == "listo" for v in [manual_data.get("elo_local"), manual_data.get("elo_visitante")]) else 0,
        "odds": 16 if (odds_data or {}).get("resumen") else 0,
        "stats_sec": 10 if any(_availability_label(v) == "listo" for v in [home.get("shots_on_goal"), away.get("shots_on_goal"), home.get("corners"), away.get("corners")]) else 0,
        "tabla": 8 if any(_availability_label((side.get("tabla") or {}).get("pos")) == "listo" for side in [home, away]) else 0,
        "contexto": 6 if (_availability_label(manual_data.get("contexto_libre")) == "listo" or context_info.get("confianza_contexto")) else 0,
    }
    score = sum(bloques.values())
    if score >= 80:
        nivel = "alta"
    elif score >= 60:
        nivel = "media"
    else:
        nivel = "baja"
    return {"score": score, "nivel": nivel, "bloques": bloques}


def _market_specific_score(candidate, home, away, lambda_local, lambda_visitante):
    key = candidate["key"]
    score = 0.0
    motivos = []

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
        if shots_local > shots_visit + 1:
            score += 0.08
            motivos.append("mejor volumen ofensivo local")
        if pos_local > pos_visit + 6:
            score += 0.04
            motivos.append("mayor control del partido")
    elif key == "visitante":
        if lambda_visitante > lambda_local + 0.20:
            score += 0.16
            motivos.append("visita con mejor produccion esperada")
        if shots_visit > shots_local + 1:
            score += 0.08
            motivos.append("visita con mejor volumen ofensivo")
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
    elif key == "under25":
        total_lambda = lambda_local + lambda_visitante
        if total_lambda <= 2.15:
            score += 0.18
            motivos.append("lambda total contenida")
        if (shots_local + shots_visit) <= 6 and (shots_local + shots_visit) > 0:
            score += 0.08
            motivos.append("poco volumen de remate")
    elif key == "btts_si":
        if lambda_local >= 1.15 and lambda_visitante >= 0.95:
            score += 0.15
            motivos.append("ambos equipos tienen ruta de gol")
        if shots_local >= 3 and shots_visit >= 3:
            score += 0.08
            motivos.append("ambos generan remate al arco")
    elif key == "btts_no":
        if lambda_local < 1.0 or lambda_visitante < 0.8:
            score += 0.14
            motivos.append("uno de los dos equipos proyecta poco gol")
        if min(shots_local, shots_visit) <= 2:
            score += 0.06
            motivos.append("un lado llega con poco volumen")

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
            "contexto_libre": _availability_label(manual_data.get("contexto_libre")),
            "contexto_estructurado": "listo" if manual_data.get("contexto_ollama") else ("listo" if context_info.get("confianza_contexto") else "faltante"),
        },
    }


def _build_reasoning_summary(best_candidate, sistemas_a_favor, sistemas_total, confidence, prob_final, ev, context_info, quality_info):
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
    if best_candidate and best_candidate.get("market_fit_reasons"):
        motivos.append("Perfil mercado: " + ", ".join(best_candidate.get("market_fit_reasons", [])[:3]))

    bloqueos = []
    if ev <= 0:
        bloqueos.append("EV no positivo")
    if confidence < 0.65:
        bloqueos.append("confianza por debajo del umbral")
    if sistemas_a_favor < 5:
        bloqueos.append("menos de 5 sistemas a favor")
    if quality_info.get("score", 0) < 55:
        bloqueos.append("calidad de input insuficiente")
    if best_candidate and best_candidate.get("market_fit_score", 0) < 0.10:
        bloqueos.append("mercado sin confirmacion especifica suficiente")

    return {
        "decision": "PICK" if (ev > 0 and confidence >= 0.65 and sistemas_a_favor >= 5) else "NO BET",
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


def _candidate_support(candidate, poisson_probs, dc_probs, elo_prob, forma_diff, xg_adj_local, xg_adj_visit, odds_data, home, away, lambda_local, lambda_visitante):
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
    market_fit_score, market_fit_reasons = _market_specific_score(candidate, home, away, lambda_local, lambda_visitante)
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

    lambda_local, lambda_visitante = _lambda_base(home, away)
    poisson_matrix = _score_matrix(lambda_local, lambda_visitante)
    poisson_probs = _matrix_market_probs(poisson_matrix)

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
    quality_info = _input_quality_score(home, away, manual_data, odds_data, context_info)
    favorite_signal = _favorite_structure_signal(poisson_probs, elo_prob, forma_diff)

    candidates = _build_candidates(poisson_probs, odds_data)
    evaluated_candidates = []
    for candidate in candidates:
        systems_candidate, apoyos, neutrales, meta = _candidate_support(
            candidate, poisson_probs, dc_probs, elo_prob, forma_diff, xg_adj_local, xg_adj_visit, odds_data, home, away, lambda_local, lambda_visitante
        )
        candidate_copy = dict(candidate)
        candidate_copy["systems"] = systems_candidate
        candidate_copy["sistemas_a_favor"] = apoyos
        candidate_copy["sistemas_neutrales"] = neutrales
        candidate_copy.update(meta)
        guardrail_penalty, guardrail_alerts = _candidate_guardrails(candidate_copy, favorite_signal, elo_prob, forma_diff)
        candidate_copy["guardrail_penalty"] = guardrail_penalty
        candidate_copy["guardrail_alerts"] = guardrail_alerts
        candidate_copy["score_candidato"] = round(
            (candidate_copy["ev"] * 3.2)
            + (candidate_copy["prob_modelo"] * 0.8)
            + (apoyos * 0.09)
            + (candidate_copy.get("market_fit_score", 0) * 0.75)
            + (neutrales * 0.01),
            4,
        )
        candidate_copy["score_ajustado"] = round(candidate_copy["score_candidato"] - guardrail_penalty, 4)
        evaluated_candidates.append(candidate_copy)

    evaluated_candidates.sort(
        key=lambda x: (x["sistemas_a_favor"], x["score_ajustado"], x["ev"], x["prob_modelo"]),
        reverse=True,
    )
    best_candidate = evaluated_candidates[0] if evaluated_candidates else None

    target_key = best_candidate["key"] if best_candidate else None
    target_prob = best_candidate["prob_modelo"] if best_candidate else None
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
        "contexto_reglado": {
            "ajuste_total": context_info["ajuste_total"],
            "confianza_contexto": context_info["confianza_contexto"],
            "resumen": context_info["resumen"],
            "veredicto": "apoya" if context_info["ajuste_total"] > 0.01 else ("no_apoya" if context_info["ajuste_total"] < -0.01 else "neutral"),
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
    if best_candidate and best_candidate["ev"] <= 0:
        riesgos.append("El valor esperado no supera 0.")
    if confidence < 0.65:
        riesgos.append("La confianza agregada sigue por debajo del umbral operativo.")
    if best_candidate and best_candidate["mercado"] != "1X2" and best_candidate["sistemas_a_favor"] < 5:
        riesgos.append("El mercado secundario no tiene apoyo suficiente.")
    if quality_info["nivel"] == "baja":
        riesgos.append("La calidad del input es baja; el motor penalizo la confianza.")
    elif quality_info["nivel"] == "media":
        riesgos.append("La calidad del input es intermedia; conviene revisar antes de publicar.")
    if best_candidate and best_candidate.get("market_fit_score", 0) < 0.12:
        riesgos.append("El mercado elegido no tiene suficiente confirmacion especifica por perfil de juego.")
    if best_candidate and best_candidate.get("guardrail_alerts"):
        riesgos.extend(best_candidate.get("guardrail_alerts", []))

    emitido = bool(
        best_candidate
        and sistemas_a_favor >= 5
        and confidence >= 0.65
        and ev > 0
        and quality_info["score"] >= 55
        and best_candidate.get("market_fit_score", 0) >= 0.10
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
