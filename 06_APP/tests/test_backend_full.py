import pytest
import pandas as pd
import numpy as np
import os
import asyncio
from unittest.mock import MagicMock, patch

from core.judge import (
    consolidar_picks, 
    _calcular_calidad_mercado, 
    _aplicar_penalizacion_cuota
)
from core.metrics import calcular_metricas_riesgo
from backtest_engine import es_handicap_asiatico, calcular_metricas
from pdf_generator import generar_pdf_pick_oficial

# ==============================================================================
# TESTS PARA core/judge.py 
# ==============================================================================

def test_calidad_mercado_boundaries():
    """Verifica los umbrales de calidad de mercado según la cuota."""
    assert _calcular_calidad_mercado(2.0) == 1.0
    assert _calcular_calidad_mercado(1.3) == 0.75
    val_bajo = _calcular_calidad_mercado(1.1)
    assert 0 < val_bajo < 0.5
    assert _calcular_calidad_mercado(10.0) == 0.0

def test_penalizacion_cuota_impacto():
    """Verifica el castigo al score en cuotas extremas con precisión flotante."""
    score_ini = 0.8
    assert _aplicar_penalizacion_cuota(score_ini, 1.1) == pytest.approx(0.45)
    assert _aplicar_penalizacion_cuota(score_ini, 7.0) == pytest.approx(0.6)
    assert _aplicar_penalizacion_cuota(score_ini, 2.0) == score_ini


# ==============================================================================
# TESTS PARA core/metrics.py
# ==============================================================================

def test_metricas_riesgo_calculo():
    """Verifica cálculos matemáticos de métricas de riesgo."""
    df = pd.DataFrame([
        {"stake": 10, "ganancia": 10, "resultado": "ganada", "cuota_real": 2.0},
        {"stake": 10, "ganancia": -10, "resultado": "perdida", "cuota_real": 2.0},
        {"stake": 10, "ganancia": 5, "resultado": "ganada", "cuota_real": 1.5},
    ])
    m = calcular_metricas_riesgo(df, 100)
    assert m["ganadas"] == 2
    assert m["profit_factor"] == 1.5
    assert m["yield_porcentaje"] == 16.67


# ==============================================================================
# TESTS PARA backtest_engine.py
# ==============================================================================

@patch("backtest_engine.get_all_picks")
@patch("backtest_engine.get_bankroll_inicial")
def test_backtest_flow(mock_bank, mock_picks):
    """Verifica el flujo del motor de backtest simulado con columnas completas."""
    mock_bank.return_value = 1000
    mock_picks.return_value = pd.DataFrame([
        {"id": 1, "ia": "IA1", "stake": 100, "ganancia": 90, "resultado": "ganada", 
         "fecha": "2024-01-01", "cuota_real": 1.9, "partido": "A vs B"},
        {"id": 2, "ia": "IA1", "stake": 100, "ganancia": -100, "resultado": "perdida", 
         "fecha": "2024-01-02", "cuota_real": 1.9, "partido": "C vs D"},
    ])
    res = calcular_metricas()
    assert res["bankroll_actual"] == 990
    assert res["total_picks"] == 2

def test_check_handicap():
    """Verifica detección de handicap asiático."""
    assert es_handicap_asiatico("-0.25")
    assert not es_handicap_asiatico("-1.5")


# ==============================================================================
# TESTS PARA pdf_generator.py
# ==============================================================================

def test_pdf_output():
    """Verifica que el PDF se genera como bytes."""
    pick = {
        "Partido": "A vs B", "Fecha": "2024-01-01", "Mercado": "M", "Seleccion": "S",
        "Cuota Promedio": 2.0, "Confianza": 0.8, "Recomendacion": "R", "Score": 0.8, "veredicto": "Publicable"
    }
    out = generar_pdf_pick_oficial(pick)
    assert isinstance(out, bytes)


# ==============================================================================
# TESTS DE PESOS IA
# ==============================================================================

def test_ia_weights_impact():
    """Confirma que los pesos de las IAs afectan el score al haber discrepancia."""
    # IA_A apuesta por Seleccion S1, IA_B apuesta por Seleccion S2
    df = pd.DataFrame([
        {"partido": "P", "ia": "IA_A", "mercado": "M", "seleccion": "S1", "cuota": 2.0, "confianza": 0.8},
        {"partido": "P", "ia": "IA_B", "mercado": "M", "seleccion": "S2", "cuota": 2.0, "confianza": 0.8},
    ])
    
    # Si IA_A tiene mucho peso (10) y IA_B poco (1), el score de S1 debe ser alto
    res1 = consolidar_picks(df, {"IA_A": 10.0, "IA_B": 1.0})
    score_s1_high = next(r["Score"] for r in res1 if r["Seleccion"] == "S1")
    
    # Si IA_A tiene poco peso (0.1) y IA_B mucho (1), el score de S1 debe bajar
    res2 = consolidar_picks(df, {"IA_A": 0.1, "IA_B": 1.0})
    score_s1_low = next(r["Score"] for r in res2 if r["Seleccion"] == "S1")
    
    assert score_s1_high > score_s1_low
