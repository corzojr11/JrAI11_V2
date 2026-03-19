import json
import math

import pandas as pd


def _to_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _clasificar_veredicto(score, consenso, total_ias, confianza):
    quorum_fuerte = max(3, math.ceil(total_ias * 0.45))
    quorum_minimo = max(2, math.ceil(total_ias * 0.30))

    if consenso < 2 or score < 0.45:
        return "Descartar", "Muy debil"
    if consenso >= quorum_fuerte and score >= 0.72 and confianza >= 0.68:
        return "Publicable", "Fuerte"
    if consenso >= quorum_minimo and score >= 0.58 and confianza >= 0.60:
        return "Vigilar", "Moderada"
    return "Debil", "Baja"


def consolidar_picks(pendientes, pesos, incluir_alternativas=False):
    """
    Consolida picks pendientes con una lectura mas util que el conteo simple.
    Considera:
    - numero de IAs alineadas
    - peso historico acumulado
    - confianza ponderada
    - sanidad basica de cuota
    """
    if not incluir_alternativas and "tipo_pick" in pendientes.columns:
        pendientes = pendientes[pendientes["tipo_pick"] == "principal"]

    if pendientes.empty:
        return []

    pendientes = pendientes.copy()
    pendientes["cuota_num"] = pendientes["cuota"].apply(_to_float)
    pendientes["confianza_num"] = pendientes["confianza"].apply(_to_float)
    pendientes["peso_ia"] = pendientes["ia"].apply(lambda ia: _to_float(pesos.get(ia, 1.0), 1.0))

    total_ias = max(1, int(pendientes["ia"].nunique()))
    pesos_totales = max(
        1.0,
        sum(_to_float(pesos.get(ia, 1.0), 1.0) for ia in pendientes["ia"].dropna().unique()),
    )

    grupos = pendientes.groupby(["partido", "mercado", "seleccion"], dropna=False)
    resultados = []

    for (partido, mercado, seleccion), grupo in grupos:
        consenso = int(grupo["ia"].nunique())
        cuota_promedio = grupo["cuota_num"].mean() if not grupo.empty else 0.0
        suma_pesos = grupo["peso_ia"].sum()
        confianza_ponderada = (
            (grupo["confianza_num"] * grupo["peso_ia"]).sum() / suma_pesos if suma_pesos > 0 else 0.0
        )

        consenso_ratio = consenso / total_ias
        peso_ratio = suma_pesos / pesos_totales
        score = (consenso_ratio * 0.40) + (peso_ratio * 0.35) + (confianza_ponderada * 0.25)

        # Penaliza picks poco publicables o demasiado extremos.
        if cuota_promedio and cuota_promedio < 1.18:
            score -= 0.05
        elif cuota_promedio and cuota_promedio > 6.0:
            score -= 0.07

        score = max(0.0, min(score, 1.0))
        veredicto, recomendacion = _clasificar_veredicto(score, consenso, total_ias, confianza_ponderada)

        resultados.append(
            {
                "Partido": partido,
                "Mercado": mercado,
                "Seleccion": seleccion,
                "Cuota Promedio": round(cuota_promedio, 2),
                "Consenso": consenso,
                "Cobertura IA %": round(consenso_ratio * 100, 1),
                "Peso acumulado": round(suma_pesos, 2),
                "Peso relativo %": round(peso_ratio * 100, 1),
                "Confianza Ponderada": round(confianza_ponderada, 2),
                "Score": round(score, 2),
                "Recomendacion": recomendacion,
                "veredicto": veredicto,
            }
        )

    resultados.sort(
        key=lambda x: (x["Score"], x["Consenso"], x["Confianza Ponderada"], x["Cuota Promedio"]),
        reverse=True,
    )
    return resultados


def guardar_veredicto(resultados, archivo="veredicto_final.json"):
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
