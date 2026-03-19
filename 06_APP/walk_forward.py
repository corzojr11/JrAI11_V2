import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.weighting import calcular_peso_bayesiano
from backtest_engine import calcular_metricas_riesgo

DB_PATH = "data/backtest.db"

def load_picks():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM picks WHERE resultado != 'pendiente' ORDER BY fecha", conn)
    conn.close()
    # Convertir fecha a datetime
    df['fecha'] = pd.to_datetime(df['fecha'])
    return df

def walk_forward_analysis(df, n_splits=5, test_days=30):
    """
    Realiza walk-forward validation.
    df: DataFrame con picks ordenados por fecha.
    n_splits: número de ventanas.
    test_days: tamaño de la ventana de prueba en días.
    """
    resultados = []
    fechas = df['fecha'].sort_values().unique()
    if len(fechas) < n_splits * 2:
        print(f"❌ Pocas fechas: {len(fechas)}. Necesitas al menos {n_splits*2} para walk-forward.")
        return

    # Calcular el tamaño de cada ventana de entrenamiento
    total_dias = (fechas[-1] - fechas[0]).days
    train_days = total_dias - (n_splits * test_days)
    if train_days < test_days:
        print("⚠️ Período de entrenamiento muy corto. Ajustando...")
        train_days = test_days * 2

    for i in range(n_splits):
        test_start = fechas[0] + timedelta(days=train_days + i * test_days)
        test_end = test_start + timedelta(days=test_days)
        train_end = test_start - timedelta(days=1)

        # Filtrar datos
        train_df = df[df['fecha'] <= train_end]
        test_df = df[(df['fecha'] >= test_start) & (df['fecha'] <= test_end)]

        if train_df.empty or test_df.empty:
            print(f"⚠️ Ventana {i+1}: entrenamiento vacío o prueba vacía. Saltando.")
            continue

        # Calcular pesos con entrenamiento
        # Replicamos lógica de calcular_metricas (simplificada)
        train_retornos = train_df['ganancia'] / train_df['stake']
        roi_global = train_retornos.mean() * 100

        pesos = {}
        for ia in train_df['ia'].unique():
            ia_df = train_df[train_df['ia'] == ia]
            n = len(ia_df)
            roi = ia_df['ganancia'].sum() / ia_df['stake'].sum() * 100 if ia_df['stake'].sum() > 0 else 0
            ret = ia_df['ganancia'] / ia_df['stake']
            sharpe = (ret.mean() / ret.std() * np.sqrt(365)) if ret.std() > 0 else 0
            peso = calcular_peso_bayesiano(roi, n, sharpe, roi_global)
            pesos[ia] = peso

        # Evaluar en prueba
        test_retornos = test_df['ganancia'] / test_df['stake']
        roi_test = test_retornos.mean() * 100
        sharpe_test = (test_retornos.mean() / test_retornos.std() * np.sqrt(365)) if test_retornos.std() > 0 else 0
        # Calcular drawdown en prueba (simple)
        bankroll_test = 1000  # base simulada
        cum_test = test_df['ganancia'].cumsum()
        max_val = cum_test.cummax()
        drawdown = ((cum_test - max_val) / max_val).min() if not cum_test.empty else 0

        # Si quieres más métricas, puedes usar calcular_metricas_riesgo pero requiere bankroll inicial
        # Simplemente guardamos ROI y Sharpe
        resultados.append({
            'ventana': i+1,
            'train_desde': train_df['fecha'].min().strftime('%Y-%m-%d'),
            'train_hasta': train_end.strftime('%Y-%m-%d'),
            'test_desde': test_start.strftime('%Y-%m-%d'),
            'test_hasta': test_end.strftime('%Y-%m-%d'),
            'n_train': len(train_df),
            'n_test': len(test_df),
            'roi_test': round(roi_test, 2),
            'sharpe_test': round(sharpe_test, 3),
            'drawdown_test': round(drawdown * 100, 2) if not cum_test.empty else 0,
            'pesos': pesos
        })

    df_result = pd.DataFrame(resultados)
    print("\n📊 **RESULTADOS WALK-FORWARD**")
    print(df_result[['ventana', 'test_desde', 'test_hasta', 'n_test', 'roi_test', 'sharpe_test', 'drawdown_test']].to_string(index=False))

    # Promedios
    print("\n📈 **PROMEDIO**")
    print(f"ROI promedio en prueba: {df_result['roi_test'].mean():.2f}%")
    print(f"Sharpe promedio: {df_result['sharpe_test'].mean():.3f}")
    print(f"Drawdown promedio: {df_result['drawdown_test'].mean():.2f}%")

    return df_result

if __name__ == "__main__":
    df = load_picks()
    if df.empty:
        print("❌ No hay datos en la base de datos.")
    else:
        walk_forward_analysis(df, n_splits=5, test_days=30)