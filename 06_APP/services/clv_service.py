import logging
from database import get_conn
from core.utils import normalizar_linea_25, es_mercado_clv_valido, normalizar_seleccion_canonica

logger = logging.getLogger(__name__)

def registrar_closing_odds_seguro(pick_id, cuota_cierre, seleccion_cierre=None):
    """
    Registra la cuota de cierre validando la comparabilidad contra el pick original en DB.
    
    Solo acepta:
    - Mercados 1X2 (Resultado Final).
    - Mercados Over/Under con línea exactamente 2.5.
    - La selección (lado) debe coincidir canónicamente con la original del pick.
    """
    if not pick_id or not cuota_cierre or float(cuota_cierre) <= 1.0:
        return False, "ID de pick o cuota de cierre inválida."

    if not seleccion_cierre:
        return False, "Se requiere la selección (lado) de la cuota de cierre para validar comparabilidad."

    try:
        with get_conn() as conn:
            # 1. Recuperar pick original para validación interna
            pick = conn.execute(
                "SELECT mercado, seleccion, linea FROM picks WHERE id = ?", 
                (int(pick_id),)
            ).fetchone()
            
            if not pick:
                return False, f"Pick con ID {pick_id} no encontrado en la base de datos."
            
            mercado_orig, seleccion_orig, linea_orig = pick
            tipo_mercado = es_mercado_clv_valido(mercado_orig)
            
            # 2. Validaciones de Seguridad y Alcance
            if not tipo_mercado:
                return False, f"Mercado '{mercado_orig}' fuera de alcance CLV v1.2 (Solo 1X2 o O/U)."

            # Validación de Selección mediante Normalización Canónica
            sel_orig_canonica = normalizar_seleccion_canonica(seleccion_orig, tipo_mercado)
            sel_cierre_canonica = normalizar_seleccion_canonica(seleccion_cierre, tipo_mercado)
            
            if not sel_orig_canonica:
                return False, f"No se pudo normalizar la selección original '{seleccion_orig}' para el mercado {tipo_mercado}."
            
            if not sel_cierre_canonica:
                return False, f"No se pudo normalizar la selección de cierre '{seleccion_cierre}' para el mercado {tipo_mercado}."

            if sel_orig_canonica != sel_cierre_canonica:
                return False, f"Selección no coincide: '{sel_orig_canonica}' vs '{sel_cierre_canonica}'."
            
            if tipo_mercado == "OU25":
                linea_norm = normalizar_linea_25(linea_orig)
                if linea_norm is None:
                    return False, f"Línea O/U '{linea_orig}' no es comparable (se requiere 2.5)."
            
            # 3. Registro en DB
            conn.execute(
                "UPDATE picks SET cuota_cierre = ? WHERE id = ?",
                (float(cuota_cierre), int(pick_id))
            )
            
            logger.info(f"✅ CLV registrado para pick {pick_id}: Cuota cierre {cuota_cierre} ({sel_cierre_canonica})")
            return True, "Cuota de cierre (CLV) registrada correctamente."
            
    except Exception as e:
        logger.error(f"❌ Error registrando CLV para pick {pick_id}: {e}")
        return False, f"Error interno: {str(e)}"
