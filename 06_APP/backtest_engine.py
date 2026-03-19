# backtest_engine.py
import pandas as pd
import plotly.express as px
import numpy as np
from scipy import stats
from database import get_all_picks, get_bankroll_inicial
from core.metrics import calcular_metricas_riesgo

def calcular_metricas(incluir_alternativas=False):
    df = get_all_picks(incluir_alternativas=incluir_alternativas)
    df_res = df[df['resultado'] != 'pendiente'].copy()
    
    if df_res.empty:
        return {
            'bankroll_actual': get_bankroll_inicial(),
            'total_picks': len(df),
            'ganadas': 0, 'perdidas': 0, 'medias': 0,
            'roi_global': 0.0, 'yield_global': 0.0,
            'df_ia': pd.DataFrame(), 
            'evolucion': pd.DataFrame(),
            'metricas_riesgo': {}
        }
    
    gan_neta = df_res['ganancia'].sum()
    volumen = df_res['stake'].sum()
    roi = (gan_neta / volumen * 100) if volumen > 0 else 0
    yield_ = gan_neta / (len(df_res) * df_res['stake'].iloc[0]) if len(df_res) > 0 else 0
    
    # Métricas por IA
    df_ia = df_res.groupby('ia').agg(
        picks=('id','count'),
        ganadas=('resultado', lambda x: (x=='ganada').sum()),
        perdidas=('resultado', lambda x: (x=='perdida').sum()),
        medias=('resultado', lambda x: (x=='media').sum()),
        ganancia_neta=('ganancia','sum'),
        volumen=('stake','sum')
    ).reset_index()
    df_ia['roi'] = (df_ia['ganancia_neta'] / df_ia['volumen'] * 100).round(1)
    
    # Evolución del bankroll
    df_sorted = df_res.sort_values('fecha')
    df_sorted['bankroll'] = get_bankroll_inicial() + df_sorted['ganancia'].cumsum()
    df_sorted['fecha'] = pd.to_datetime(df_sorted['fecha'])
    
    # Calcular métricas de riesgo
    metricas_riesgo = calcular_metricas_riesgo(df_res, get_bankroll_inicial())
    
    return {
        'bankroll_actual': round(get_bankroll_inicial() + gan_neta, 2),
        'total_picks': len(df),
        'ganadas': (df_res['resultado']=='ganada').sum(),
        'perdidas': (df_res['resultado']=='perdida').sum(),
        'medias': (df_res['resultado']=='media').sum(),
        'roi_global': round(roi, 1),
        'yield_global': round(yield_*100, 1),
        'df_ia': df_ia,
        'evolucion': df_sorted[['fecha', 'bankroll', 'partido']],
        'metricas_riesgo': metricas_riesgo
    }

def es_handicap_asiatico(seleccion: str) -> bool:
    return any(x in seleccion for x in ['.25', '.75', '+0.25', '-0.25', '+0.75', '-0.75'])