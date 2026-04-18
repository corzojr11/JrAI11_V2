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


def _clasificar_veredicto(score, consenso, total_ias, calidad_mercado):
    """
    Clasifica el veredicto basado en score (que ya incluye confianza),
    consenso y calidad de mercado.
    """
    quorum_fuerte = max(3, math.ceil(total_ias * 0.45))
    quorum_minimo = max(2, math.ceil(total_ias * 0.30))

    if consenso < 2 or score < 0.45:
        return "Descartar", "Muy debil"
    if consenso >= quorum_fuerte and score >= 0.72 and calidad_mercado >= 0.65:
        return "Publicable", "Fuerte"
    if consenso >= quorum_minimo and score >= 0.58 and calidad_mercado >= 0.55:
        return "Vigilar", "Moderada"
    return "Debil", "Baja"


def consolidar_picks(pendientes, pesos, incluir_alternativas=False):
    """
    Consolida picks individuales de IAs en veredictos unificados.
    
    Formula del Score (0.0 a 1.0):
    - Consenso (40%): Fracción de IAs activas que coinciden en el mismo pick.
    - Peso Historico (35%): Relevancia acumulada de las IAs según su rendimiento pasado.
    - Confianza (15%): Promedio de grados de confianza declarados por las IAs para este pick.
    - Calidad Mercado (10%): Valoración del rango de cuota (óptimo 1.50 - 3.50).
    
    Adicionalmente, se aplica _aplicar_penalizacion_cuota() para castigar picks con cuotas 
    extremedamente bajas (<1.20) o muy altas (>5.0) para proteger el bankroll.
    """
    if pendientes is None or (isinstance(pendientes, pd.DataFrame) and pendientes.empty):
        return []

    # Filtrado por tipo si existe la columna
    if not incluir_alternativas and "tipo_pick" in pendientes.columns:
        pendientes = pendientes[pendientes["tipo_pick"] == "principal"]

    if pendientes.empty:
        return []

    pendientes = pendientes.copy()
    pendientes["cuota_num"] = pendientes["cuota"].apply(_to_float)
    pendientes["confianza_num"] = pendientes["confianza"].apply(_to_float)
    pendientes["peso_ia"] = pendientes["ia"].apply(lambda ia: _to_float(pesos.get(ia, 1.0), 1.0))

    # Estadísticas para normalización
    total_ias = max(1, int(pendientes["ia"].nunique()))
    # Suma de pesos de todas las IAs únicas que emitieron picks
    pesos_totales = max(
        0.01,
        sum(_to_float(pesos.get(ia, 1.0), 1.0) for ia in pendientes["ia"].dropna().unique()),
    )

    grupos = pendientes.groupby(["partido", "mercado", "seleccion"], dropna=False)
    resultados = []

    for (partido, mercado, seleccion), grupo in grupos:
        consenso = int(grupo["ia"].nunique())
        cuota_promedio = grupo["cuota_num"].mean() if not grupo.empty else 0.0
        suma_pesos = grupo["peso_ia"].sum()
        confianza_promedio = grupo["confianza_num"].mean() if not grupo.empty else 0.0
        
        # 1. Calidad de mercado (basada solo en cuota)
        calidad_mercado = _calcular_calidad_mercado(cuota_promedio)

        # 2. Ratios normalizados
        consenso_ratio = consenso / total_ias
        peso_ratio = min(1.0, suma_pesos / pesos_totales)
        
        # 3. Cálculo de Score (ver docstring para pesos)
        score = (consenso_ratio * 0.40) + \
                (peso_ratio * 0.35) + \
                (confianza_promedio * 0.15) + \
                (calidad_mercado * 0.10)

        # 4. Penalizaciones de seguridad
        score = _aplicar_penalizacion_cuota(score, cuota_promedio)

        # 5. Acotamiento final [0, 1]
        score = max(0.0, min(float(score), 1.0))
        
        veredicto, recomendacion = _clasificar_veredicto(score, consenso, total_ias, calidad_mercado)

        resultados.append(
            {
                "Partido": str(partido or "Desconocido"),
                "Mercado": str(mercado or "Variable"),
                "Seleccion": str(seleccion or "N/A"),
                "Cuota Promedio": round(cuota_promedio, 2),
                "Consenso": consenso,
                "Cobertura IA %": round(consenso_ratio * 100, 1),
                "Peso acumulado": round(suma_pesos, 2),
                "Peso relativo %": round(peso_ratio * 100, 1),
                "Calidad Mercado": round(calidad_mercado, 2),
                "Score": round(score, 2),
                "Recomendacion": recomendacion,
                "veredicto": veredicto,
            }
        )

    # Ordenar por relevancia
    resultados.sort(
        key=lambda x: (x["Score"], x["Consenso"], x["Calidad Mercado"]),
        reverse=True,
    )
    return resultados


def _calcular_calidad_mercado(cuota):
    """
    Evalua el rango de la cuota.
    Prioriza cuotas optimas (1.5 - 3.5) por estabilidad estadistica.
    """
    if cuota <= 0:
        return 0.0
    
    if 1.50 <= cuota <= 3.50:
        return 1.0
    if 1.18 <= cuota < 1.50:
        return 0.75
    if 3.50 < cuota <= 5.00:
        return 0.70
    
    if cuota > 5.00:
        return max(0.0, 0.5 - (cuota - 5.0) * 0.1)
    if cuota < 1.18:
        return max(0.0, 0.5 - (1.18 - cuota) * 2.0)
    
    return 0.5


def _aplicar_penalizacion_cuota(score, cuota):
    """
    Castigo directo al score para picks de alto riesgo por cuota extrema.
    """
    if cuota <= 0:
        return score
    
    if cuota < 1.15:
        # Cuotas ínfimas / Sin valor real
        return max(0.0, score - 0.35)
    elif cuota < 1.25:
        # Cuotas muy bajas
        return max(0.0, score - 0.12)
    elif cuota > 6.0:
        # Cuotas muy altas / Outliers
        return max(0.0, score - 0.20)
    elif cuota > 4.5:
        # Cuotas altas / Riesgo
        return max(0.0, score - 0.08)
    
    return score


def guardar_veredicto(resultados, archivo="veredicto_final.json"):
    """Persiste veredictos en JSON."""
    try:
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(resultados, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error guardando veredicto: {e}")

