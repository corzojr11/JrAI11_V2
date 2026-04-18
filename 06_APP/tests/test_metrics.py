"""
Tests de métricas y backtest.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMetricas:
    """Tests para métricas de rendimiento."""
    
    def test_calcular_metricas_retorna_dict(self):
        """Test que retorna diccionario con campos esperados."""
        from backtest_engine import calcular_metricas
        metricas = calcular_metricas()
        assert isinstance(metricas, dict)
        assert "bankroll_actual" in metricas
        assert "ganadas" in metricas
        assert "perdidas" in metricas
        assert "medias" in metricas
        assert "yield_global" in metricas


class TestHandicapAsiatico:
    """Tests para handicap asiático."""
    
    def test_es_handicap_asiatico(self):
        """Test detección de handicap asiático."""
        from backtest_engine import es_handicap_asiatico
        
        assert es_handicap_asiatico("-0.25") == True
        assert es_handicap_asiatico("-0.75") == True
        assert es_handicap_asiatico("-1.25") == True
        assert es_handicap_asiatico("+0.25") == True
        assert es_handicap_asiatico("+0.75") == True
        
        assert es_handicap_asiatico("-1") == False
        assert es_handicap_asiatico("-0.5") == False
        assert es_handicap_asiatico("+1") == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
