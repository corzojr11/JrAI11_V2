import pandas as pd
import plotly.express as px
import numpy as np
from scipy import stats
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

def conditional_cache(**kwargs):
    def decorator(func):
        if HAS_STREAMLIT:
            try:
                # Importación tardía para no penalizar el tiempo de importación del módulo
                from streamlit.runtime import exists
                if exists():
                    # st.cache_data solo se aplica si la app está corriendo genuinamente
                    return st.cache_data(**kwargs)(func)
            except (ImportError, AttributeError):
                pass
        return func
    return decorator

from database import get_all_picks, get_bankroll_inicial
from core.metrics import calcular_metricas_riesgo

@conditional_cache(ttl=300)
def calcular_metricas(incluir_alternativas=False, fecha_inicio=None, fecha_fin=None):
    df = get_all_picks(incluir_alternativas=incluir_alternativas)

    if df is not None and not df.empty and "fecha" in df.columns:
        fechas = pd.to_datetime(df["fecha"], errors="coerce")
        mask = fechas.notna()
        if fecha_inicio:
            mask &= fechas >= pd.to_datetime(fecha_inicio, errors="coerce")
        if fecha_fin:
            mask &= fechas <= pd.to_datetime(fecha_fin, errors="coerce")
        df = df.loc[mask].copy()
    
    # Robustez: Si el DF está vacío o no tiene la columna de resultado, devolver estructura base
    if df is None or df.empty or 'resultado' not in df.columns:
        return {
            'bankroll_inicial': get_bankroll_inicial(),
            'bankroll_actual': get_bankroll_inicial(),
            'total_picks': 0,
            'ganadas': 0, 'perdidas': 0, 'medias': 0,
            'roi_global': 0.0, 'yield_global': 0.0,
            'fecha_min': None,
            'fecha_max': None,
            'serie_diaria': [],
            'df_ia': pd.DataFrame(), 
            'evolucion': pd.DataFrame(),
            'metricas_riesgo': {}
        }
        
    df_res = df[df['resultado'] != 'pendiente'].copy()
    
    if df_res.empty:
        return {
            'bankroll_inicial': get_bankroll_inicial(),
            'bankroll_actual': get_bankroll_inicial(),
            'total_picks': len(df),
            'ganadas': 0, 'perdidas': 0, 'medias': 0,
            'roi_global': 0.0, 'yield_global': 0.0,
            'fecha_min': None,
            'fecha_max': None,
            'serie_diaria': [],
            'df_ia': pd.DataFrame(), 
            'evolucion': pd.DataFrame(),
            'metricas_riesgo': {}
        }
    
    bankroll_inicial = get_bankroll_inicial()
    gan_neta = df_res['ganancia'].sum()
    volumen = df_res['stake'].sum()
    roi = (gan_neta / volumen * 100) if volumen > 0 else 0
    yield_ = gan_neta / (len(df_res) * df_res['stake'].iloc[0]) if len(df_res) > 0 else 0
    
    fechas = pd.to_datetime(df_res["fecha"], errors="coerce").dropna()
    fecha_min = fechas.min().date().isoformat() if not fechas.empty else None
    fecha_max = fechas.max().date().isoformat() if not fechas.empty else None

    df_serie = df_res.copy()
    df_serie["fecha_dt"] = pd.to_datetime(df_serie["fecha"], errors="coerce")
    df_serie = df_serie.dropna(subset=["fecha_dt"]).sort_values("fecha_dt")
    if not df_serie.empty:
        serie_diaria = (
            df_serie.assign(fecha_dia=df_serie["fecha_dt"].dt.date)
            .groupby("fecha_dia", as_index=False)
            .agg(
                ganancia_neta=("ganancia", "sum"),
                stake_total=("stake", "sum"),
                picks=("id", "count"),
            )
        )
        serie_diaria["bankroll"] = bankroll_inicial + serie_diaria["ganancia_neta"].cumsum()
        serie_diaria["roi_dia"] = serie_diaria.apply(
            lambda row: (row["ganancia_neta"] / row["stake_total"] * 100) if row["stake_total"] else 0,
            axis=1,
        )
        serie_diaria["fecha"] = serie_diaria["fecha_dia"].astype(str)
        serie_diaria = serie_diaria[["fecha", "bankroll", "ganancia_neta", "stake_total", "picks", "roi_dia"]]
        serie_diaria = serie_diaria.to_dict(orient="records")
    else:
        serie_diaria = []
    
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
    metricas_riesgo = calcular_metricas_riesgo(df_res, bankroll_inicial)
    
    return {
        'bankroll_inicial': bankroll_inicial,
        'bankroll_actual': round(bankroll_inicial + gan_neta, 2),
        'total_picks': len(df),
        'ganadas': (df_res['resultado']=='ganada').sum(),
        'perdidas': (df_res['resultado']=='perdida').sum(),
        'medias': (df_res['resultado']=='media').sum(),
        'roi_global': round(roi, 1),
        'yield_global': round(yield_*100, 1),
        'fecha_min': fecha_min,
        'fecha_max': fecha_max,
        'serie_diaria': serie_diaria,
        'df_ia': df_ia,
        'evolucion': df_sorted[['fecha', 'bankroll', 'partido']],
        'metricas_riesgo': metricas_riesgo
    }

def es_handicap_asiatico(seleccion: str) -> bool:
    return any(x in seleccion for x in ['.25', '.75', '+0.25', '-0.25', '+0.75', '-0.75'])
