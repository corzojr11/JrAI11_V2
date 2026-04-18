import numpy as np
from scipy import stats


def calcular_metricas_riesgo(df, bankroll_inicial):
    """
    Calcula metricas avanzadas de riesgo/rendimiento.
    
    Sharpe se calcula como ratio simple (no anualizado) para mantener consistencia
    con el número de apuestas real.
    """
    if df.empty:
        return {}

    df = df.copy()
    stake_total = df["stake"].sum()
    ganancia_neta = df["ganancia"].fillna(0).sum()
    
    # Yield/ROI: porcentaje de ganancia sobre stake total
    yield_porcentaje = (ganancia_neta / stake_total * 100) if stake_total > 0 else 0
    
    stake_valido = df["stake"].replace(0, np.nan)
    retornos = (df["ganancia"] / stake_valido).replace([np.inf, -np.inf], np.nan).dropna()
    if retornos.empty:
        return {}

    # Sharpe simple (no anualizado) - ratio media/desv
    sharpe = (
        retornos.mean() / retornos.std()
        if retornos.std() and retornos.std() > 0
        else 0
    )
    
    # Mantener sharpe_ratio para compatibilidad hacia atrás (pero con fórmula corregida)
    sharpe_ratio = sharpe

    # Tasa de acierto
    resultados = df["resultado"].fillna("media")
    ganadas = (resultados == "ganada").sum()
    perdidas = (resultados == "perdida").sum()
    medias = (resultados == "media").sum()
    total_con_resultado = ganadas + perdidas
    tasa_acierto = (ganadas / total_con_resultado * 100) if total_con_resultado > 0 else 0
    
    ganadas_str = int(ganadas)
    perdidas_str = int(perdidas)
    medias_str = int(medias)

    bankroll = bankroll_inicial + df["ganancia"].fillna(0).cumsum()
    running_max = bankroll.cummax().replace(0, np.nan)
    drawdown = ((bankroll - running_max) / running_max).replace([np.inf, -np.inf], np.nan).fillna(0)
    max_drawdown = drawdown.min()

    ganancias_totales = df[df["ganancia"] > 0]["ganancia"].sum()
    perdidas_totales = abs(df[df["ganancia"] < 0]["ganancia"].sum())
    profit_factor = ganancias_totales / perdidas_totales if perdidas_totales > 0 else float("inf")

    df["ev"] = df.apply(
        lambda row: row["cuota_real"] - 1
        if row["resultado"] == "ganada"
        else (-1 if row["resultado"] == "perdida" else 0),
        axis=1,
    )
    ev_promedio = df["ev"].mean()

    resultados = df["resultado"].values
    racha_actual = 0
    racha_max_ganadora = 0
    racha_max_perdedora = 0
    for res in resultados:
        if res == "ganada":
            racha_actual = racha_actual + 1 if racha_actual >= 0 else 1
        elif res == "perdida":
            racha_actual = racha_actual - 1 if racha_actual <= 0 else -1
        else:
            continue
        racha_max_ganadora = max(racha_max_ganadora, racha_actual)
        racha_max_perdedora = min(racha_max_perdedora, racha_actual)

    if len(retornos) < 2:
        p_value = 1.0
    else:
        _, p_value = stats.ttest_1samp(retornos, 0)
        if np.isnan(p_value):
            p_value = 1.0

    return {
        "sharpe": round(float(sharpe), 4),
        "sharpe_ratio": round(float(sharpe_ratio), 4),  # Compatibilidad
        "max_drawdown": round(float(max_drawdown) * 100, 2),
        "profit_factor": round(float(profit_factor), 2),
        "ev_promedio": round(float(ev_promedio), 3),
        "yield_porcentaje": round(float(yield_porcentaje), 2),
        "tasa_acierto": round(float(tasa_acierto), 2),
        "ganadas": ganadas_str,
        "perdidas": perdidas_str,
        "medias": medias_str,
        "racha_max_ganadora": int(racha_max_ganadora),
        "racha_max_perdedora": abs(int(racha_max_perdedora)),
        "p_value": round(float(p_value), 4),
        "significativo_95": p_value < 0.05,
    }


def calcular_analisis_clv(df):
    """
    Cálculo de métricas de CLV con control de cobertura y comparabilidad estricta.
    """
    from core.utils import es_mercado_clv_valido, normalizar_linea_25

    if df.empty:
        return {
            "avg_clv_percent": 0.0,
            "beat_clv_rate": 0.0,
            "clv_sample_size": 0,
            "clv_coverage_rate": 0.0
        }

    # 1. Identificar universo elegible (Picks que podrían tener CLV)
    def es_elegible(row):
        tipo = es_mercado_clv_valido(row.get('mercado'))
        if tipo == "1X2": return True
        if tipo == "OU25": 
            return normalizar_linea_25(row.get('linea')) == 2.5
        return False

    df_elegible = df[df.apply(es_elegible, axis=1)].copy()
    
    if df_elegible.empty:
        return {
            "avg_clv_percent": 0.0,
            "beat_clv_rate": 0.0,
            "clv_sample_size": 0,
            "clv_coverage_rate": 0.0
        }

    # 2. Picks con CLV realmente capturado (no NULL en DB)
    # En pandas, las columnas REAL NULL de SQLite cargan como NaN
    df_capturado = df_elegible[df_elegible["cuota_cierre"].notna()].copy()
    # Asegurar que cuota_cierre sea > 1.0 (filtro de seguridad adicional)
    df_capturado = df_capturado[df_capturado["cuota_cierre"] > 1.0]
    
    clv_sample_size = len(df_capturado)
    clv_coverage_rate = (clv_sample_size / len(df_elegible)) * 100

    if clv_sample_size == 0:
        return {
            "avg_clv_percent": 0.0,
            "beat_clv_rate": 0.0,
            "clv_sample_size": 0,
            "clv_coverage_rate": round(clv_coverage_rate, 2)
        }

    # 3. Cálculo de Edge: (Cuota_Inicial / Cuota_Cierre) - 1
    # Nota: Usamos la cuota base del pick (cuota) vs la de cierre (cuota_cierre)
    df_capturado["clv_factor"] = (df_capturado["cuota"] / df_capturado["cuota_cierre"]) - 1
    
    avg_clv = df_capturado["clv_factor"].mean()
    beat_rate = (df_capturado["clv_factor"] > 0).sum() / clv_sample_size * 100
    
    return {
        "avg_clv_percent": round(float(avg_clv) * 100, 2),
        "beat_clv_rate": round(float(beat_rate), 2),
        "clv_sample_size": clv_sample_size,
        "clv_coverage_rate": round(float(clv_coverage_rate), 2)
    }
