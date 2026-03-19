# core/weighting.py
import numpy as np

def calcular_peso_bayesiano(roi, n_picks, sharpe, global_roi=0.0, prior_n=20):
    """
    Calcula peso con shrinkage bayesiano + Sharpe.
    """
    # 1. Shrinkage hacia la media global
    shrunk_roi = (n_picks * roi + prior_n * global_roi) / (n_picks + prior_n)
    
    # 2. Factor de consistencia (Sharpe) - limitado para no desbocar
    sharpe_factor = max(0.5, min(1.5, 1 + sharpe / 2))
    
    # 3. Peso base
    peso_base = 1 + shrunk_roi / 100
    
    # 4. Ajustar por Sharpe y número de picks
    peso = peso_base * sharpe_factor * np.log10(n_picks + 10) / 2
    
    # 5. Limitar a rango razonable
    return round(max(0.1, min(3.0, peso)), 3)