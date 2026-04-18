import json

import requests


OLLAMA_CONTEXT_PROMPT = """Analiza el contexto deportivo y responde SOLO un JSON valido.

Debes evaluar:
- lesiones confirmadas
- motivacion competitiva
- arbitro y perfil
- rotaciones o alineaciones
- si el partido es liga o eliminatoria
- si existe ida/vuelta o marcador global
- urgencia real de puntos o clasificacion
- racha reciente si aparece
- cambios de ultimo momento realmente importantes

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

Reglas importantes:
- No resumas de forma generica si el contexto trae detalles concretos.
- Si aparece una baja muy sensible, arquero debutante, marcador global, necesidad de remontar, racha negativa o arbitro tarjetero, debes reflejarlo en los ajustes.
- Si el texto dice que NO es eliminatoria o que NO hay ida/vuelta, tenlo en cuenta y no lo inventes.
- Prioriza hechos verificables por encima de frases vacias.
- No expliques nada fuera del JSON.
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
- No hagas resumenes genericos si el texto trae detalles mas fuertes.
- Prioriza, cuando existan:
  - posicion y puntos reales;
  - pelea de clasificacion, titulo o descenso;
  - ida/vuelta o marcador global;
  - racha reciente importante;
  - bajas confirmadas relevantes;
  - arquero debutante o cambio fuerte de once;
  - perfil del arbitro si es realmente llamativo.
- `motivacion_local` y `motivacion_visitante` deben sonar operativos, no vacios.
- `contexto_adicional` debe concentrar los factores mas potentes del partido que afecten lectura y riesgo.
- Si falta informacion, redacta prudente y neutral.
- No des picks ni recomendaciones de apuesta.
- No expliques nada fuera del JSON.

Ejemplo de buena salida:
{
  "motivacion_local": "Llega fuera del top 8, con cinco partidos sin ganar y urgencia real por recortar distancia con la zona de clasificacion.",
  "motivacion_visitante": "Llega en puestos de octavos, pero con margen corto y bajas sensibles que le obligan a proteger resultado y rendimiento.",
  "contexto_adicional": "No es eliminatoria. La novedad fuerte es el arquero debutante del visitante y un arbitro de promedio alto de tarjetas, en un partido de tension competitiva."
}
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
        "options": {"temperature": 0.2},
    }
    try:
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
        if resp.status_code != 200:
            return None, f"Ollama respondio HTTP {resp.status_code}: {resp.text[:200]}"
        
        data = resp.json()
        raw = str(data.get("response", "") or "").strip()
        if not raw:
            return None, "Ollama devolvió una respuesta vacía."
            
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None, f"Ollama devolvió un JSON invalido: {raw[:100]}"

        # Aplicar saneamiento y valores por defecto
        parsed["ajuste_total"] = max(-0.15, min(0.15, float(parsed.get("ajuste_total", 0.0))))
        parsed["confianza_contexto"] = max(0.0, min(1.0, float(parsed.get("confianza_contexto", 0.0))))
        parsed["resumen"] = str(parsed.get("resumen", "") or "").strip()[:220]
        return parsed, ""
        
    except requests.exceptions.Timeout:
        return None, "Timeout consultando Ollama (120s)."
    except requests.exceptions.ConnectionError:
        return None, "No se pudo conectar con Ollama. ¿Está el servicio activo?"
    except Exception as e:
        return None, f"Error inesperado en Ollama: {str(e)}"


def sugerir_campos_contexto_ollama(texto_contexto, modelo="qwen2.5:14b"):
    texto_contexto = str(texto_contexto or "").strip()
    if not texto_contexto:
        return None, "No hay informacion suficiente para sugerir el contexto."

    payload = {
        "model": modelo,
        "prompt": f"{OLLAMA_TEXT_FIELDS_PROMPT}\n\nCONTEXTO DEL PARTIDO:\n{texto_contexto}",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
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
