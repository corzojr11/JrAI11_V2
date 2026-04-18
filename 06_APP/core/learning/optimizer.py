"""
Módulo de Recalibración y Aprendizaje del Motor Propio.
Analiza el histórico de resultados en la BD para ajustar los pesos de los subsistemas.
"""
from core.motor.weights import get_system_weights, update_weights
from database import get_all_picks
import pandas as pd

def run_weights_optimization():
    """
    Ejecuta un ciclo de optimización heurística sobre los pesos del motor
    basado en el ROI histórico reciente del Motor-Propio.
    Retorna un diccionario con el ROI actual, los pesos anteriores y los nuevos.
    """
    current_weights = get_system_weights()
    df = get_all_picks(incluir_alternativas=False)
    
    if df is None or df.empty:
        return {"status": "insufficient_data", "message": "No hay suficientes datos para optimizar."}
        
    motor_picks = df[df["ia"] == "Motor-Propio"]
    resueltos = motor_picks[motor_picks["resultado"].isin(["ganada", "perdida", "media"])]
    
    if len(resueltos) < 10:
        return {
            "status": "insufficient_data", 
            "message": f"Solo hay {len(resueltos)} picks resueltos del Motor. Se requieren 10 mínimo para evitar overfitting."
        }
    
    total_stake = resueltos["stake"].sum()
    ganancia_neta = resueltos["ganancia"].sum()
    
    roi = (ganancia_neta / total_stake) if total_stake > 0 else 0.0
    hit_rate = len(resueltos[resueltos["resultado"] == "ganada"]) / len(resueltos)
    
    new_weights = dict(current_weights)
    
    # Heurística simple de adaptación al mercado:
    # Si estamos perdiendo dinero (ROI < 0), la intuición del mercado (mercado_eficiente) 
    # suele ser mas precisa (sabiduría de masas). 
    # Por tanto, shiftamos pesos hacia 'mercado_eficiente' y 'arbitraje_lineas'.
    # Si ganamos dinero (ROI > 0), confiamos mas en nuestro núcleo matemático puro (poisson, elo).
    
    learning_rate = 0.02 # ajuste suave
    
    if roi < -0.05:
        # Penalizamos matemáticas lentas, premiamos señales de mercado rápido
        new_weights["poisson"] = max(0.10, new_weights.get("poisson", 0.30) - learning_rate)
        new_weights["elo"] = max(0.10, new_weights.get("elo", 0.15) - learning_rate)
        new_weights["mercado_eficiente"] = min(0.30, new_weights.get("mercado_eficiente", 0.05) + (learning_rate * 1.5))
        new_weights["forma_ponderada"] = min(0.20, new_weights.get("forma_ponderada", 0.10) + (learning_rate * 0.5))
    elif roi > 0.05:
        # Reforzamos el núcleo matemático que esta dando valor
        new_weights["poisson"] = min(0.40, new_weights.get("poisson", 0.30) + learning_rate)
        new_weights["elo"] = min(0.25, new_weights.get("elo", 0.15) + (learning_rate * 0.5))
        new_weights["forma_ponderada"] = max(0.05, new_weights.get("forma_ponderada", 0.10) - (learning_rate * 0.5))
        new_weights["mercado_eficiente"] = max(0.02, new_weights.get("mercado_eficiente", 0.05) - learning_rate)
        
    # Normalizar via función propia
    success = update_weights(new_weights)
    
    if success:
        return {
            "status": "success",
            "roi": round(roi, 4),
            "hit_rate": round(hit_rate, 4),
            "sample_size": len(resueltos),
            "old_weights": current_weights,
            "new_weights": get_system_weights()
        }
    else:
        return {"status": "error", "message": "Fallo la normalización de pesos."}
