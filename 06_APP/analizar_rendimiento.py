# analizar_rendimiento.py
import sqlite3
import pandas as pd
import numpy as np
import json
from scipy import stats
from core.weighting import calcular_peso_bayesiano

DB_PATH = "data/backtest.db"
OUTPUT_FILE = "pesos_ia.json"

def calcular_metricas():
    print("🔍 Calculando nuevas métricas con fórmula mejorada...")
    
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM picks WHERE resultado != 'pendiente'", conn)
    conn.close()
    
    if df.empty:
        print("❌ No hay picks con resultado registrado.")
        return
    
    df['retorno'] = df['ganancia'] / df['stake']
    roi_global = df['retorno'].mean() * 100
    
    resultados = []
    for ia in df['ia'].unique():
        df_ia = df[df['ia'] == ia]
        n_picks = len(df_ia)
        ganancias = df_ia['ganancia'].values
        retornos = df_ia['retorno'].values
        
        roi = ganancias.sum() / df_ia['stake'].sum() * 100 if df_ia['stake'].sum() > 0 else 0
        sharpe = (retornos.mean() / retornos.std() * np.sqrt(365)) if retornos.std() > 0 else 0
        cv = retornos.std() / abs(retornos.mean()) if retornos.mean() != 0 else float('inf')
        
        peso = calcular_peso_bayesiano(roi, n_picks, sharpe, roi_global)
        
        if n_picks > 0:
            wins = (df_ia['resultado'] == 'ganada').sum()
            ci_low, ci_high = stats.binomtest(wins, n_picks).proportion_ci(confidence_level=0.95)
        else:
            ci_low = ci_high = 0
        
        resultados.append({
            'ia': ia,
            'picks': n_picks,
            'roi': round(roi, 2),
            'sharpe': round(sharpe, 3),
            'cv': round(cv, 3),
            'peso_nuevo': peso,
            'ci_95': (round(ci_low, 3), round(ci_high, 3))
        })
    
    df_resultados = pd.DataFrame(resultados).sort_values('peso_nuevo', ascending=False)
    
    print("\n📊 **NUEVOS PESOS CALCULADOS (Shrinkage + Sharpe)**")
    print(df_resultados[['ia', 'picks', 'roi', 'sharpe', 'peso_nuevo']].to_string(index=False))
    
    pesos = dict(zip(df_resultados['ia'], df_resultados['peso_nuevo']))
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(pesos, f, indent=2)
    print(f"\n✅ Pesos guardados en {OUTPUT_FILE}")
    
    return df_resultados

if __name__ == "__main__":
    calcular_metricas()