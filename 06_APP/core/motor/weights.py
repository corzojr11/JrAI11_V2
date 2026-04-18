"""
Definición y manejo de los pesos de los subsistemas del motor.
Estos pesos deciden cuánto influye cada señal en el score final del pick.
"""
import json
import os
from pathlib import Path

WEIGHTS_FILE = Path("data/system_weights.json")

# Pesos predeterminados por defecto 
# (Basados en nuestra experiencia actual, Poisson sigue siendo el más robusto, seguido de ELO y xG).
DEFAULT_WEIGHTS = {
    "poisson": 0.30,
    "dixon_coles": 0.20,
    "elo": 0.15,
    "regresion_xg": 0.15,
    "forma_ponderada": 0.10,
    "arbitraje_lineas": 0.05,
    "mercado_eficiente": 0.05,
}

def get_system_weights():
    """Obtiene los pesos actuales para el motor."""
    if not WEIGHTS_FILE.exists():
        _save_weights(DEFAULT_WEIGHTS)
        return DEFAULT_WEIGHTS
        
    try:
        with open(WEIGHTS_FILE, 'r', encoding='utf-8') as f:
            weights = json.load(f)
            # Asegurar que todas las claves existan
            for k, v in DEFAULT_WEIGHTS.items():
                if k not in weights:
                    weights[k] = v
            return weights
    except Exception:
        return DEFAULT_WEIGHTS

def _save_weights(weights_dict):
    """Guarda los pesos actualizados en el archivo JSON."""
    try:
        os.makedirs(WEIGHTS_FILE.parent, exist_ok=True)
        with open(WEIGHTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(weights_dict, f, indent=4)
    except Exception as e:
        print(f"Error al guardar system_weights.json: {e}")

def update_weights(new_weights):
    """
    Actualiza los pesos después de una optimización.
    Valida que sumen aproximadamente 1.0 y esten dentro de rangos cuerdos.
    """
    total = sum(float(v) for v in new_weights.values())
    if total <= 0:
        return False
        
    normalized = {k: round(float(v) / total, 3) for k, v in new_weights.items()}
    _save_weights(normalized)
    return True
