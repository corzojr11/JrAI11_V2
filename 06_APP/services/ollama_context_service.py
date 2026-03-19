import json

import requests


OLLAMA_CONTEXT_PROMPT = """Analiza el contexto deportivo y responde SOLO un JSON valido.

Debes evaluar:
- lesiones confirmadas
- motivacion competitiva
- arbitro y perfil
- rotaciones o alineaciones

Devuelve unicamente este objeto:
{
  "ajuste_lesiones": numero entre -0.15 y 0,
  "ajuste_motivacion": numero entre -0.05 y 0.05,
  "ajuste_arbitro": numero entre -0.03 y 0.03,
  "ajuste_rotaciones": numero entre -0.10 y 0,
  "ajuste_total": suma de los anteriores limitada entre -0.15 y 0.15,
  "confianza_contexto": numero entre 0 y 1,
  "resumen": "maximo 2 lineas"
}

No expliques nada fuera del JSON.
"""


OLLAMA_TEXT_FIELDS_PROMPT = """Eres un asistente de preparacion de partidos.

Con la informacion entregada, redacta SOLO un JSON valido para rellenar estos campos de la app:
{
  "motivacion_local": "texto breve, 1 o 2 lineas",
  "motivacion_visitante": "texto breve, 1 o 2 lineas",
  "contexto_adicional": "texto breve, 1 o 2 lineas"
}

Reglas:
- No inventes lesiones, rotaciones ni noticias que no aparezcan en el contexto.
- Si falta informacion, redacta prudente y neutral.
- No des picks ni recomendaciones de apuesta.
- No expliques nada fuera del JSON.
"""


def analizar_contexto_ollama(texto_contexto, modelo="qwen2.5:14b"):
    texto_contexto = str(texto_contexto or "").strip()
    if not texto_contexto:
        return None, "No hay texto de contexto para analizar."

    payload = {
        "model": modelo,
        "prompt": f"{OLLAMA_CONTEXT_PROMPT}\n\nCONTEXTO:\n{texto_contexto}",
        "stream": False,
        "format": "json",
    }
    try:
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
        if resp.status_code != 200:
            return None, f"Ollama respondio HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        raw = str(data.get("response", "") or "").strip()
        parsed = json.loads(raw)
        parsed["ajuste_total"] = max(-0.15, min(0.15, float(parsed.get("ajuste_total", 0.0))))
        parsed["confianza_contexto"] = max(0.0, min(1.0, float(parsed.get("confianza_contexto", 0.0))))
        parsed["resumen"] = str(parsed.get("resumen", "") or "").strip()[:220]
        return parsed, ""
    except Exception as e:
        return None, f"No se pudo consultar Ollama local: {e}"


def sugerir_campos_contexto_ollama(texto_contexto, modelo="qwen2.5:14b"):
    texto_contexto = str(texto_contexto or "").strip()
    if not texto_contexto:
        return None, "No hay informacion suficiente para sugerir el contexto."

    payload = {
        "model": modelo,
        "prompt": f"{OLLAMA_TEXT_FIELDS_PROMPT}\n\nCONTEXTO DEL PARTIDO:\n{texto_contexto}",
        "stream": False,
        "format": "json",
    }
    try:
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
        if resp.status_code != 200:
            return None, f"Ollama respondio HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        raw = str(data.get("response", "") or "").strip()
        parsed = json.loads(raw)
        resultado = {
            "motivacion_local": str(parsed.get("motivacion_local", "") or "").strip()[:280],
            "motivacion_visitante": str(parsed.get("motivacion_visitante", "") or "").strip()[:280],
            "contexto_adicional": str(parsed.get("contexto_adicional", "") or "").strip()[:320],
        }
        return resultado, ""
    except Exception as e:
        return None, f"No se pudo generar el contexto automatico con Ollama: {e}"
