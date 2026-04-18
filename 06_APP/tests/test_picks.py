"""
Tests de picks - guardado y carga.
"""
import pytest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPicks:
    """Tests para guardado y carga de picks."""
    
    def test_get_all_picks(self, temp_db):
        """Test obtener todos los picks."""
        from database import get_all_picks
        picks = get_all_picks()
        assert picks is not None
    
    def test_save_pick(self, temp_db, clean_user):
        """Test guardar un pick."""
        from database import save_picks
        import pandas as pd
        pick_df = pd.DataFrame([{
            "fecha": datetime.now().strftime("%Y-%m-%d"),
            "partido": "Real Madrid vs Barcelona",
            "ia": "TestIA",
            "mercado": "Ganador",
            "seleccion": "Real Madrid",
            "cuota": 2.0,
            "confianza": 0.75,
            "stake": 1.0,
            "resultado": "pendiente",
            "tipo_pick": "principal",
        }])
        
        resultado = save_picks(pick_df, f"test_{clean_user}")
        assert isinstance(resultado, dict)
        assert "insertados" in resultado
    
    def test_save_pick_con_datos_completos(self, temp_db, clean_user):
        """Test guardar pick con todos los campos."""
        from database import save_picks
        import pandas as pd
        pick_df = pd.DataFrame([{
            "fecha": "2026-03-19",
            "partido": "Team A vs Team B",
            "ia": "Gemini",
            "mercado": "Over 2.5",
            "seleccion": "Over 2.5",
            "cuota": 1.85,
            "confianza": 0.80,
            "stake": 2.0,
            "analisis_breve": "Análisis de prueba",
            "competicion": "LaLiga",
            "resultado": "pendiente",
            "tipo_pick": "principal",
        }])
        
        resultado = save_picks(pick_df, f"test_{clean_user}")
        assert isinstance(resultado, dict)


class TestPicksResults:
    """Tests para resultados de picks."""
    
    def test_get_picks_por_estado(self, temp_db):
        """Test obtener picks por estado."""
        from database import get_all_picks
        picks = get_all_picks()
        
        if picks is not None and not picks.empty:
            pendientes = picks[picks.get("resultado", "") == "pendiente"]
            assert isinstance(pendientes, type(picks))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
