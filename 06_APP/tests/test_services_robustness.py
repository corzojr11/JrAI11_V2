import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json
import asyncio
import requests

from services.match_prepare_service import _api_get
from services.ai_analysis import _llamar_gemini, _llamar_groq, _llamar_ollama, _resultado_error
from services.ollama_context_service import analizar_contexto_ollama

# ==============================================================================
# TESTS PARA match_prepare_service._api_get (Requests/Sync)
# ==============================================================================

def test_api_get_retries_on_500_then_success():
    """Verifica que _api_get reintenta tras un error 500 y tiene éxito."""
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 500
    
    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.json.return_value = {"response": [{"id": 1}], "errors": {}}
    
    with patch("requests.get", side_effect=[mock_resp_fail, mock_resp_success]) as mock_get:
        # Forzar API key activa para el test
        with patch("services.match_prepare_service.API_FOOTBALL_KEY", "fake_key"):
            response, error = _api_get("/test")
            
            assert response == [{"id": 1}]
            assert error is None
            assert mock_get.call_count == 2

def test_api_get_timeout_exhausted():
    """Verifica que _api_get falla tras agotar reintentos por timeout."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout) as mock_get:
        with patch("services.match_prepare_service.API_FOOTBALL_KEY", "fake_key"):
            response, error = _api_get("/test")
            
            assert response is None
            assert "Timeout" in error
            assert mock_get.call_count == 3  # 1 inicial + 2 reintentos

def test_api_get_invalid_json():
    """Verifica manejo de respuesta que no es JSON válido."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = "No soy un dict"
    
    with patch("requests.get", return_value=mock_resp):
        with patch("services.match_prepare_service.API_FOOTBALL_KEY", "fake_key"):
            response, error = _api_get("/test")
            assert response is None
            assert "no es un objeto JSON valido" in error


# ==============================================================================
# TESTS PARA AI_ANALYSIS (Aiohttp/Async)
# ==============================================================================

def test_gemini_no_candidates():
    """Verifica que Gemini maneja respuesta 200 OK pero sin candidatos."""
    async def run_test():
        class MockResp:
            def __init__(self): self.status = 200
            async def json(self): return {"candidates": []}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            
        class MockSession:
            def post(self, *args, **kwargs): return MockResp()
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            res = await _llamar_gemini("Auto-Gemini-Contextual", "prompt", "key")
            assert res["status"] == "error"
            assert "no devolvio candidatos" in res["error"]
            
    asyncio.run(run_test())

def test_groq_timeout_retry():
    """Verifica que Groq maneja timeout con reintentos."""
    async def run_test():
        # Simulamos que el post directamente lanza TimeoutError al ser llamado
        class MockSession:
            def post(self, *args, **kwargs):
                raise asyncio.TimeoutError()
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            with patch("services.ai_analysis._esperar_turno_groq", return_value=None):
                res = await _llamar_groq("Auto-Groq-Contraste", "prompt", "key")
                assert res["status"] == "error"
                assert "Timeout" in res["error"]
                
    asyncio.run(run_test())

def test_ollama_empty_body():
    """Verifica que Ollama maneja respuesta vacía."""
    async def run_test():
        class MockResp:
            def __init__(self): self.status = 200
            async def json(self): return {"response": ""}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            
        class MockSession:
            def post(self, *args, **kwargs): return MockResp()
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            res = await _llamar_ollama("Auto-Ollama-Conservador", "prompt", "llama3")
            assert res["status"] == "error"
            assert "JSON invalido" in res["error"]
            
    asyncio.run(run_test())


# ==============================================================================
# TESTS PARA ollama_context_service (Requests/Sync)
# ==============================================================================

def test_ollama_context_connection_error():
    """Verifica que ollama_context detecta servicio apagado."""
    with patch("requests.post", side_effect=requests.exceptions.ConnectionError):
        res, error = analizar_contexto_ollama("contexto")
        assert res is None
        assert "No se pudo conectar" in error

def test_ollama_context_invalid_json():
    """Verifica sanación de JSON malformado de Ollama."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "Esto no es un JSON"}
    
    with patch("requests.post", return_value=mock_resp):
        res, error = analizar_contexto_ollama("contexto")
        assert res is None
        assert "JSON invalido" in error


# ==============================================================================
# TEST DE CONTRATO DE ERROR
# ==============================================================================

def test_resultado_error_structure():
    """Confirma que la estructura de error es la que app.py espera."""
    res = _resultado_error("Mi-IA", "Hubo un fallo", "output sucio")
    assert res["ia"] == "Mi-IA"
    assert res["status"] == "error"
    assert res["error"] == "Hubo un fallo"
    assert "raw_output" in res
