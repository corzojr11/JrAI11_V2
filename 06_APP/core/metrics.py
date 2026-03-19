import numpy as np
from scipy import stats


def calcular_metricas_riesgo(df, bankroll_inicial):
    """
    Calcula metricas avanzadas de riesgo/rendimiento.
    """
    if df.empty:
        return {}

    df = df.copy()
    stake_valido = df["stake"].replace(0, np.nan)
    retornos = (df["ganancia"] / stake_valido).replace([np.inf, -np.inf], np.nan).dropna()
    if retornos.empty:
        return {}

    sharpe = (
        retornos.mean() / retornos.std() * np.sqrt(365)
        if retornos.std() and retornos.std() > 0
        else 0
    )

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
        "sharpe_ratio": round(float(sharpe), 3),
        "max_drawdown": round(float(max_drawdown) * 100, 2),
        "profit_factor": round(float(profit_factor), 2),
        "ev_promedio": round(float(ev_promedio), 3),
        "racha_max_ganadora": int(racha_max_ganadora),
        "racha_max_perdedora": abs(int(racha_max_perdedora)),
        "p_value": round(float(p_value), 4),
        "significativo_95": p_value < 0.05,
    }
