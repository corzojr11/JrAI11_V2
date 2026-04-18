"""
Tests del Judge - consolidación de picks.
"""
import pytest
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestJudge:
    """Tests para el sistema de judge/consenso."""
    
    def test_consolidar_picks_vacio(self):
        """Test robusto para entrada vacía."""
        from core.judge import consolidar_picks
        # Caso DataFrame vacío
        assert consolidar_picks(pd.DataFrame(), {}) == []
        # Caso None
        assert consolidar_picks(None, {}) == []
    
    def test_consenso_y_cuota_razonable(self):
        """Test: Consenso alto con cuota en rango óptimo produce score alto."""
        from core.judge import consolidar_picks
        df = pd.DataFrame([
            {"partido": "A vs B", "ia": "IA1", "mercado": "O2.5", "seleccion": "O2.5", "cuota": 1.90, "confianza": 0.8},
            {"partido": "A vs B", "ia": "IA2", "mercado": "O2.5", "seleccion": "O2.5", "cuota": 1.95, "confianza": 0.7},
            {"partido": "A vs B", "ia": "IA3", "mercado": "O2.5", "seleccion": "O2.5", "cuota": 1.85, "confianza": 0.9},
        ])
        pesos = {"IA1": 1.0, "IA2": 1.0, "IA3": 1.0}
        resultado = consolidar_picks(df, pesos)
        
        assert len(resultado) == 1
        res = resultado[0]
        assert res["Consenso"] == 3
        assert res["Score"] >= 0.70  # Debería ser publicable/fuerte
        assert res["veredicto"] == "Publicable"

    def test_consenso_aparente_cuota_extrema(self):
        """Test: Consenso alto pero cuota absurda (penalización)."""
        from core.judge import consolidar_picks
        df = pd.DataFrame([
            {"partido": "X vs Y", "ia": "IA1", "mercado": "Gana", "seleccion": "X", "cuota": 1.05, "confianza": 0.9},
            {"partido": "X vs Y", "ia": "IA2", "mercado": "Gana", "seleccion": "X", "cuota": 1.06, "confianza": 0.9},
        ])
        pesos = {"IA1": 1.0, "IA2": 1.0}
        resultado = consolidar_picks(df, pesos)
        
        res = resultado[0]
        # El score debe bajar por la penalización de cuota baja (<1.20)
        assert res["Score"] < 0.60 
        assert res["veredicto"] != "Publicable"

    def test_estructura_retorno_estable(self):
        """Verifica que las claves de retorno coincidan con lo esperado por app.py."""
        from core.judge import consolidar_picks
        df = pd.DataFrame([
            {"partido": "P1", "ia": "IA1", "mercado": "M1", "seleccion": "S1", "cuota": 2.0, "confianza": 0.5}
        ])
        resultado = consolidar_picks(df, {"IA1": 1.0})
        pick = resultado[0]
        
        claves_obligatorias = [
            "Partido", "Mercado", "Seleccion", "Cuota Promedio", 
            "Consenso", "Score", "Recomendacion", "veredicto"
        ]
        for clave in claves_obligatorias:
            assert clave in pick, f"Falta clave crítica: {clave}"


class TestVeredicto:
    """Tests para veredictos."""
    
    def test_guardar_veredicto(self, tmp_path):
        """Test guardado seguro en archivo temporal."""
        from core.judge import guardar_veredicto
        archivo = tmp_path / "test_veredicto.json"
        datos = [{"test": "ok"}]
        guardar_veredicto(datos, archivo=str(archivo))
        assert os.path.exists(archivo)



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
