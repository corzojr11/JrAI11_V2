"""
Modulo de automatizacion multi-IA para JrAI11.
Soporta: Gemini, Groq, OpenRouter, SambaNova y Ollama.
"""

import asyncio
import ast
import json
import os
import re
from collections import deque
from time import monotonic

from dotenv import load_dotenv

load_dotenv()

GROQ_TPM_SEGURIDAD = 9000
GROQ_REQUESTS_POR_MINUTO = 3
GROQ_PROMPT_MAX_CHARS = 9000
GEMINI_PROMPT_MAX_CHARS = 14000
OPENROUTER_PROMPT_MAX_CHARS = 12000
SAMBANOVA_PROMPT_MAX_CHARS = 14000
OLLAMA_PROMPT_MAX_CHARS = 24000
OLLAMA_TIMEOUT_SECONDS = 600

_groq_request_log = deque()
_groq_lock = asyncio.Lock()

PERSONALIDADES = {
    "Auto-Ollama-Conservador": {
        "descripcion": "Modelo local (costo cero) para análisis estructurado y cauto.",
        "instruccion": "Eres un analista ultra conservador local. Solo emites pick si la cuota presenta valor estadistico y evitar los riesgos no controlables. Prefieres NO BET.",
    },
    "Auto-Gemini-Contextual": {
        "descripcion": "Analista de contexto humano y narrativo (lesiones, rotaciones).",
        "instruccion": "Eres un analista contextual. Priorizas factores humanos verificables: lesiones de titulares, motivacion y fatiga acumulada.",
    },
    "Auto-Groq-Contraste": {
        "descripcion": "Busca el valor en la cuota del equipo no favorito.",
        "instruccion": "Eres un analista contrarian. Buscas sistematicamente valor en el equipo que el mercado subestima. Analiza rapido las debilidades del favorito.",
    },
}


def _extraer_bloque(prompt, inicio, fin):
    match = re.search(f"{re.escape(inicio)}(.*?){re.escape(fin)}", prompt, re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _limpiar_lineas_inutiles(texto):
    lineas_utiles = []
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia:
            continue
        if "No disponible" in limpia:
            continue
        if limpia.startswith("http"):
            continue
        if limpia.startswith("[") and limpia.endswith("]"):
            continue
        lineas_utiles.append(limpia)
    return "\n".join(lineas_utiles)


def _compactar_investigacion(texto, max_chars):
    ficha = _extraer_bloque(
        texto,
        "--- INICIO FICHA DEL INVESTIGADOR ---",
        "--- FIN FICHA DEL INVESTIGADOR ---",
    )
    cuotas = _extraer_bloque(
        texto,
        "--- INICIO CUOTAS REALES ---",
        "--- FIN CUOTAS REALES ---",
    )

    if not ficha and not cuotas:
        limpio = _limpiar_lineas_inutiles(texto)
        return limpio[:max_chars]

    ficha_limpia = _limpiar_lineas_inutiles(ficha)
    cuotas_limpias = _limpiar_lineas_inutiles(cuotas)
    compacto = (
        "FICHA DEL INVESTIGADOR\n"
        f"{ficha_limpia}\n\n"
        "CUOTAS REALES\n"
        f"{cuotas_limpias}"
    ).strip()
    return compacto[:max_chars]


def _preparar_prompt_para_modelo(prompt_analista, max_chars):
    ficha = _extraer_bloque(
        prompt_analista,
        "--- INICIO FICHA DEL INVESTIGADOR ---",
        "--- FIN FICHA DEL INVESTIGADOR ---",
    )
    cuotas = _extraer_bloque(
        prompt_analista,
        "--- INICIO CUOTAS REALES ---",
        "--- FIN CUOTAS REALES ---",
    )

    if not ficha and not cuotas:
        return prompt_analista[:max_chars]

    ficha_limpia = _limpiar_lineas_inutiles(ficha)
    cuotas_limpias = _limpiar_lineas_inutiles(cuotas)

    plantilla = prompt_analista
    plantilla = re.sub(
        r"--- INICIO FICHA DEL INVESTIGADOR ---.*?--- FIN FICHA DEL INVESTIGADOR ---",
        "--- INICIO FICHA DEL INVESTIGADOR ---\n__FICHA__\n--- FIN FICHA DEL INVESTIGADOR ---",
        plantilla,
        flags=re.DOTALL,
    )
    plantilla = re.sub(
        r"--- INICIO CUOTAS REALES ---.*?--- FIN CUOTAS REALES ---",
        "--- INICIO CUOTAS REALES ---\n__CUOTAS__\n--- FIN CUOTAS REALES ---",
        plantilla,
        flags=re.DOTALL,
    )

    overhead = len(plantilla.replace("__FICHA__", "").replace("__CUOTAS__", ""))
    espacio_datos = max(1000, max_chars - overhead)
    espacio_ficha = int(espacio_datos * 0.72)
    espacio_cuotas = max(300, espacio_datos - espacio_ficha)

    prompt_final = plantilla.replace("__FICHA__", ficha_limpia[:espacio_ficha]).replace(
        "__CUOTAS__", cuotas_limpias[:espacio_cuotas]
    )
    return prompt_final[:max_chars]


async def _esperar_turno_groq():
    async with _groq_lock:
        ahora = monotonic()
        while _groq_request_log and ahora - _groq_request_log[0] > 60:
            _groq_request_log.popleft()

        if len(_groq_request_log) >= GROQ_REQUESTS_POR_MINUTO:
            espera = 60 - (ahora - _groq_request_log[0])
            if espera > 0:
                await asyncio.sleep(espera)
            ahora = monotonic()
            while _groq_request_log and ahora - _groq_request_log[0] > 60:
                _groq_request_log.popleft()

        _groq_request_log.append(monotonic())


def _extraer_json(texto):
    texto = re.sub(r"```json\s*", "", texto)
    texto = re.sub(r"```\s*", "", texto).strip()
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        return match.group(0)
    return texto


def _reparar_json_sucio(texto):
    reparado = texto.strip()
    reparado = reparado.replace("\u201c", '"').replace("\u201d", '"')
    reparado = reparado.replace("\u2018", "'").replace("\u2019", "'")
    reparado = re.sub(r",\s*([}\]])", r"\1", reparado)
    if reparado and not reparado.startswith("{") and ":" in reparado:
        reparado = "{" + reparado + "}"
    return reparado


def _parsear_json_modelo(texto):
    base = _extraer_json(texto)
    candidatos = [base, _reparar_json_sucio(base)]

    for candidato in candidatos:
        try:
            return json.loads(candidato)
        except Exception:
            pass

    for candidato in candidatos:
        try:
            valor = ast.literal_eval(candidato)
            if isinstance(valor, dict):
                return valor
        except Exception:
            pass

    preview = base[:220].replace("\n", " ")
    raise json.JSONDecodeError(f"No se pudo parsear JSON del modelo. Preview: {preview}", base, 0)


def _a_float(valor, default=0.0):
    try:
        if isinstance(valor, str):
            valor = valor.replace("%", "").replace(",", ".").strip()
        return float(valor)
    except Exception:
        return default


def _a_int(valor, default=0):
    try:
        return int(valor)
    except Exception:
        return default


def _extraer_equipos(partido):
    texto = str(partido or "").strip()
    if " vs " in texto:
        local, visita = texto.split(" vs ", 1)
        return local.strip(), visita.strip()
    return "", ""


def _normalizar_mercado(mercado):
    texto = str(mercado or "").strip()
    if not texto:
        return "Sin mercado"

    texto_l = texto.lower()
    if texto_l in {"1x2", "1x2 full time", "ganador", "resultado final"}:
        return "1X2"
    if "over" in texto_l or "under" in texto_l:
        if "corner" in texto_l:
            return texto.replace("Corners", "corners").replace("Corner", "corners")
        if "tarjet" in texto_l:
            return texto.replace("Tarjetas", "tarjetas").replace("Tarjeta", "tarjetas")
        if "gol" in texto_l:
            return texto
        return texto
    if "btts" in texto_l or "ambos anotan" in texto_l:
        return "BTTS"
    if "handicap" in texto_l or "hándicap" in texto_l:
        return "Handicap"
    if "corner" in texto_l:
        return "Corners"
    if "tarjet" in texto_l:
        return "Tarjetas"
    if "tiro" in texto_l:
        return "Tiros"
    return texto


def _normalizar_seleccion(partido, mercado, seleccion):
    texto = str(seleccion or "").strip()
    if not texto:
        return "NO BET"

    mercado_norm = _normalizar_mercado(mercado)
    local, visita = _extraer_equipos(partido)
    texto_l = texto.lower()

    if mercado_norm == "1X2":
        if texto_l in {"1", "local", "home", "home team"} and local:
            return local
        if texto_l in {"2", "visitante", "away", "away team"} and visita:
            return visita
        if texto_l in {"x", "draw", "empate"}:
            return "Empate"
    if mercado_norm == "BTTS":
        if texto_l in {"si", "sí", "yes", "y"}:
            return "Si"
        if texto_l in {"no", "n"}:
            return "No"
    if "over" in texto_l:
        return texto.replace("Sí", "Si")
    if "under" in texto_l:
        return texto.replace("Sí", "Si")
    return texto


def _normalizar_confianza(valor):
    if isinstance(valor, str):
        texto = valor.strip().lower()
        mapa = {
            "muy baja": 0.2,
            "baja": 0.35,
            "moderada": 0.55,
            "media": 0.55,
            "alta": 0.75,
            "muy alta": 0.9,
            "low": 0.35,
            "moderate": 0.55,
            "medium": 0.55,
            "high": 0.75,
            "very high": 0.9,
        }
        if texto in mapa:
            return mapa[texto]
    confianza = _a_float(valor, 0.0)
    if confianza > 1 and confianza <= 100:
        confianza = confianza / 100.0
    return max(0.0, min(confianza, 1.0))


def _contar_sistemas_favor(veredictos):
    if not isinstance(veredictos, dict):
        return 0

    total = 0
    for valor in veredictos.values():
        texto = str(valor).strip().lower()
        if texto in {"ok", "apoya", "si", "sí", "favor"}:
            total += 1
    return total


def _evaluar_cobertura_prompt(prompt_analista):
    texto = str(prompt_analista or "")
    texto_l = texto.lower()
    marcadores_faltante = [
        "sin dato",
        "sin datos",
        "sin h2h",
        "sin forma",
        "sin alineacion",
        "sin alineación",
        "sin bajas",
        "sin lesiones",
        "sin arbitro",
        "sin árbitro",
        "pendiente",
    ]
    faltantes = sum(texto_l.count(m) for m in marcadores_faltante)
    bloques_criticos = 0
    for bloque in (
        "ultimos 5 resultados",
        "h2h ultimos 5",
        "lesiones y suspensiones",
        "alineacion probable",
        "bloque 1",
        "bloque 2",
    ):
        if bloque in texto_l:
            bloques_criticos += 1
    if faltantes >= 10:
        nivel = "baja"
    elif faltantes >= 5:
        nivel = "media"
    else:
        nivel = "alta"
    return {
        "faltantes": faltantes,
        "bloques_detectados": bloques_criticos,
        "nivel": nivel,
    }


def _normalizar_pick_json(pick_json, personalidad, prompt_analista=""):
    pick = pick_json.get("pick", {}) if isinstance(pick_json.get("pick"), dict) else {}
    consenso = pick_json.get("consenso", {}) if isinstance(pick_json.get("consenso"), dict) else {}
    sistemas = (
        pick_json.get("veredictos_sistemas")
        or pick_json.get("sistemas_aplicados")
        or pick.get("veredictos_sistemas")
        or {}
    )
    analisis_resultado = (
        pick_json.get("analisis_resultado", {})
        if isinstance(pick_json.get("analisis_resultado"), dict)
        else {}
    )
    analisis_partido = (
        pick_json.get("analisis_partido", {})
        if isinstance(pick_json.get("analisis_partido"), dict)
        else {}
    )
    prediction = (
        pick_json.get("prediction", {})
        if isinstance(pick_json.get("prediction"), dict)
        else {}
    )
    pronostico = pick_json.get("pronostico")
    recomendaciones = (
        pick_json.get("recomendaciones", {})
        if isinstance(pick_json.get("recomendaciones"), dict)
        else {}
    )

    mercado_inferido = ""
    seleccion_inferida = ""
    if isinstance(pronostico, dict):
        for clave, valor in pronostico.items():
            valor_txt = str(valor).strip()
            if valor_txt and valor_txt.upper() not in {"NO BET", "NO_BET"}:
                mercado_inferido = clave
                seleccion_inferida = valor_txt
                break

    if not mercado_inferido and recomendaciones:
        for clave, valor in recomendaciones.items():
            valor_txt = str(valor).strip()
            if valor_txt and valor_txt.upper() not in {"NO BET", "NO_BET"}:
                mercado_inferido = clave
                seleccion_inferida = valor_txt
                break

    emitido = pick.get("emitido")
    if emitido is None:
        decision_raw = str(pick_json.get("decision", "")).upper().strip()
        if not decision_raw:
            decision_raw = str(pick.get("decision", "")).upper().strip()
        if not decision_raw:
            decision_raw = str(analisis_resultado.get("pick_sugerido", "")).upper().strip()
        if not decision_raw and isinstance(pronostico, str):
            decision_raw = pronostico.upper().strip()
        if not decision_raw and isinstance(pick_json.get("valor"), str):
            decision_raw = str(pick_json.get("valor")).upper().strip()
        if decision_raw:
            emitido = decision_raw not in {"NO BET", "NO_BET", "SIN PICK"}

    seleccion = (
        pick_json.get("seleccion")
        or pick.get("seleccion")
        or analisis_resultado.get("seleccion")
        or seleccion_inferida
        or "NO BET"
    )
    mercado = (
        pick_json.get("mercado")
        or pick_json.get("mercado_principal")
        or pick.get("mercado")
        or analisis_resultado.get("mercado")
        or mercado_inferido
        or "Sin mercado"
    )
    cuota = _a_float(
        pick_json.get("cuota", pick.get("cuota", analisis_resultado.get("cuota", 0)))
    )
    confianza = _normalizar_confianza(
        pick_json.get(
            "confianza",
            pick.get(
                "confianza",
                analisis_resultado.get(
                    "confianza",
                    prediction.get("confidence", 0),
                ),
            ),
        )
    )
    ev = _a_float(
        pick_json.get(
            "ev",
            pick_json.get(
                "valor_esperado",
                pick.get("valor_esperado", analisis_resultado.get("valor_esperado", 0)),
            ),
        )
    )
    stake = (
        pick_json.get("stake")
        or pick.get("stake_recomendado")
        or pick.get("stake")
        or analisis_resultado.get("stake_recomendado")
        or "0u"
    )
    sistemas_favor = _a_int(
        pick_json.get("sistemas_favor", consenso.get("sistemas_a_favor", 0))
    )
    if sistemas_favor == 0:
        sistemas_favor = _contar_sistemas_favor(sistemas)
    sistemas_total = _a_int(
        pick_json.get("sistemas_total", consenso.get("sistemas_total", 8)),
        default=8,
    )
    if sistemas_total == 0:
        sistemas_total = max(len(sistemas), 8 if sistemas else 0)
    razonamiento = (
        pick_json.get("razonamiento")
        or pick.get("razonamiento")
        or pick_json.get("motivo")
        or pick_json.get("razon")
        or analisis_resultado.get("razon_no_bet")
        or analisis_resultado.get("razonamiento")
        or (
            "; ".join(str(x) for x in pick_json.get("razones", [])[:3])
            if isinstance(pick_json.get("razones"), list)
            else ""
        )
        or (
            json.dumps(prediction.get("reasoning", {}), ensure_ascii=True)[:240]
            if isinstance(prediction.get("reasoning"), dict)
            else ""
        )
        or "Sin razonamiento disponible."
    )
    fundamentos = pick_json.get("fundamentos_clave", [])
    if not isinstance(fundamentos, list):
        fundamentos = []
    fundamentos = [str(x).strip() for x in fundamentos if str(x).strip()][:3]
    riesgo_principal = (
        str(pick_json.get("riesgo_principal", "") or "").strip()
        or str(analisis_resultado.get("riesgo_principal", "") or "").strip()
        or "Sin riesgo principal declarado."
    )
    if emitido is None:
        emitido = (
            seleccion not in {"", "NO BET", "No Bet", "Sin seleccion"}
            and cuota > 1.01
            and confianza >= 0.65
            and ev > 0
            and sistemas_favor >= 5
        )

    cobertura = _evaluar_cobertura_prompt(prompt_analista)
    if cobertura["nivel"] == "baja" and emitido:
        emitido = False
        confianza = min(confianza, 0.58)
        ev = max(0.0, ev)
        if len(fundamentos) < 3:
            fundamentos.append("Cobertura insuficiente de la ficha")
        riesgo_principal = "Faltan demasiados datos clave para sostener una entrada."
    elif cobertura["nivel"] == "media" and emitido:
        confianza = min(confianza, 0.68)
        if len(fundamentos) < 3:
            fundamentos.append("Cobertura parcial de datos")
        if not riesgo_principal or riesgo_principal == "Sin riesgo principal declarado.":
            riesgo_principal = "Cobertura parcial de datos reduce robustez del pick."

    decision = "PICK" if emitido else "NO BET"

    partido = (
        pick_json.get("partido")
        or analisis_partido.get("partido")
        or "Partido sin identificar"
    )
    mercado = _normalizar_mercado(mercado)
    seleccion = _normalizar_seleccion(partido, mercado, seleccion)

    normalizado = {
        "ia": personalidad,
        "partido": partido,
        "fecha": (
            pick_json.get("fecha")
            or analisis_partido.get("fecha")
            or analisis_partido.get("fecha_hora")
            or ""
        ),
        "mercado": mercado,
        "seleccion": seleccion,
        "cuota": cuota,
        "confianza": confianza,
        "ev": ev,
        "stake": stake,
        "sistemas_favor": sistemas_favor,
        "sistemas_total": sistemas_total,
        "veredictos_sistemas": sistemas,
        "fundamentos_clave": fundamentos,
        "riesgo_principal": riesgo_principal,
        "razonamiento": razonamiento,
        "decision": decision,
        "_cobertura_prompt": cobertura,
    }
    return normalizado


def _validar_pick_normalizado(pick):
    errores = []

    partido = str(pick.get("partido", "") or "").strip()
    mercado = str(pick.get("mercado", "") or "").strip()
    seleccion = str(pick.get("seleccion", "") or "").strip()
    decision = str(pick.get("decision", "") or "").strip().upper()
    cuota = _a_float(pick.get("cuota", 0), 0.0)
    confianza = _normalizar_confianza(pick.get("confianza", 0))
    ev = _a_float(pick.get("ev", 0), 0.0)
    sistemas_favor = _a_int(pick.get("sistemas_favor", 0), 0)
    sistemas_total = _a_int(pick.get("sistemas_total", 8), 8)
    veredictos = pick.get("veredictos_sistemas", {})
    fundamentos = pick.get("fundamentos_clave", [])
    riesgo_principal = str(pick.get("riesgo_principal", "") or "").strip()
    razonamiento = str(pick.get("razonamiento", "") or "").strip()
    cobertura_prompt = pick.get("_cobertura_prompt", {}) if isinstance(pick.get("_cobertura_prompt", {}), dict) else {}

    if not partido:
        errores.append("Falta partido")
    if decision not in {"PICK", "NO BET"}:
        errores.append("Decision invalida")
    if not mercado:
        errores.append("Falta mercado")
    if not seleccion:
        errores.append("Falta seleccion")
    if not isinstance(veredictos, dict) or not veredictos:
        errores.append("Faltan veredictos_sistemas")
    if sistemas_total < 1 or sistemas_total > 8:
        errores.append("sistemas_total invalido")
    if sistemas_favor < 0 or sistemas_favor > 8:
        errores.append("sistemas_favor invalido")
    if not isinstance(fundamentos, list) or len([x for x in fundamentos if str(x).strip()]) == 0:
        errores.append("Faltan fundamentos_clave")
    if not riesgo_principal:
        errores.append("Falta riesgo_principal")
    if not razonamiento:
        errores.append("Falta razonamiento")

    if decision == "PICK":
        if mercado in {"NO BET", "Sin mercado"}:
            errores.append("Mercado invalido para PICK")
        if seleccion in {"NO BET", "Sin seleccion"}:
            errores.append("Seleccion invalida para PICK")
        if cuota < 1.01 or cuota > 100:
            errores.append("Cuota invalida para PICK")
        if confianza < 0.65 or confianza > 1:
            errores.append("Confianza invalida para PICK")
        if ev <= 0:
            errores.append("EV no positivo para PICK")
        if sistemas_favor < 5:
            errores.append("Consenso insuficiente para PICK")
        if cobertura_prompt.get("nivel") == "baja":
            errores.append("Cobertura de datos demasiado baja para PICK")
    else:
        if cuota < 0 or cuota > 100:
            errores.append("Cuota invalida para NO BET")
        if confianza < 0 or confianza > 1:
            errores.append("Confianza invalida para NO BET")

    return len(errores) == 0, errores


def _resultado_ok(personalidad, pick_json, raw_output, prompt_analista=""):
    data = _normalizar_pick_json(pick_json, personalidad, prompt_analista=prompt_analista)
    valido, errores = _validar_pick_normalizado(data)
    return {
        "ia": personalidad,
        "status": "ok",
        "data": data,
        "valid": valido,
        "validation_errors": errores,
        "raw_output": raw_output,
    }


def _resultado_error(personalidad, error, raw_output=""):
    return {
        "ia": personalidad,
        "status": "error",
        "error": error,
        "raw_output": raw_output,
    }


async def _llamar_gemini(personalidad, prompt_analista, api_key):
    import aiohttp
    max_retries = 1
    
    for attempt in range(max_retries + 1):
        try:
            prompt_modelo = _preparar_prompt_para_modelo(
                prompt_analista,
                max_chars=GEMINI_PROMPT_MAX_CHARS,
            )
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.0-flash:generateContent?key={api_key}"
            )
            instruccion = PERSONALIDADES[personalidad]["instruccion"]
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    f"{instruccion}\n\n"
                                    "IMPORTANTE: Responde solo con JSON valido. "
                                    "Sin texto adicional ni markdown.\n\n"
                                    f"{prompt_modelo}"
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2048,
                    "responseMimeType": "application/json",
                },
            }
            
            async with aiohttp.ClientSession() as session:
                # Aumentamos timeout a 30s
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.post(url, json=payload, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if not data.get("candidates"):
                            return _resultado_error(personalidad, "Gemini no devolvio candidatos")
                        texto = data["candidates"][0]["content"]["parts"][0]["text"]
                        pick_json = _parsear_json_modelo(texto)
                        return _resultado_ok(personalidad, pick_json, texto, prompt_modelo)

                    # Reintento solo para errores de servidor
                    if resp.status in [500, 502, 503, 504] and attempt < max_retries:
                        await asyncio.sleep(2)
                        continue

                    error = await resp.text()
                    return _resultado_error(
                        personalidad,
                        f"HTTP {resp.status}: {error[:200]}",
                        error,
                    )
        except asyncio.TimeoutError:
            if attempt < max_retries:
                await asyncio.sleep(2)
                continue
            return _resultado_error(personalidad, "Timeout tras reintentos")
        except json.JSONDecodeError as e:
            return _resultado_error(personalidad, f"JSON invalido: {e}", locals().get("texto", ""))
        except Exception as e:
            return _resultado_error(personalidad, f"Error Gemini: {str(e)}")
    
    return _resultado_error(personalidad, "Fallo total en Gemini")


async def _llamar_groq(personalidad, prompt_analista, api_key):
    import aiohttp
    max_retries = 1
    
    for attempt in range(max_retries + 1):
        try:
            await _esperar_turno_groq()
            prompt_modelo = _preparar_prompt_para_modelo(
                prompt_analista,
                max_chars=GROQ_PROMPT_MAX_CHARS,
            )
            url = "https://api.groq.com/openai/v1/chat/completions"
            instruccion = PERSONALIDADES[personalidad]["instruccion"]
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{instruccion}\n\n"
                            "Responde unicamente con un JSON valido. "
                            "No expliques calculos extensos. Usa campos cortos y consistentes."
                        ),
                    },
                    {"role": "user", "content": prompt_modelo},
                ],
                "temperature": 0.2,
                "max_tokens": 900,
                "response_format": {"type": "json_object"},
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                # Aumentamos timeout a 30s
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if not data.get("choices"):
                            return _resultado_error(personalidad, "Groq no devolvió opciones")
                        texto = data["choices"][0]["message"]["content"]
                        pick_json = _parsear_json_modelo(texto)
                        return _resultado_ok(personalidad, pick_json, texto, prompt_modelo)

                    # Reintento solo para errores transitorios o Rate Limits
                    if (resp.status in [500, 502, 503, 504] or resp.status == 429) and attempt < max_retries:
                        await asyncio.sleep(3)
                        continue

                    error = await resp.text()
                    return _resultado_error(
                        personalidad,
                        f"HTTP {resp.status}: {error[:200]}",
                        error,
                    )
        except asyncio.TimeoutError:
            if attempt < max_retries:
                await asyncio.sleep(3)
                continue
            return _resultado_error(personalidad, "Timeout agotado en Groq")
        except json.JSONDecodeError as e:
            return _resultado_error(personalidad, f"JSON invalido: {e}", locals().get("texto", ""))
        except Exception as e:
            return _resultado_error(personalidad, f"Error Groq: {str(e)}")
            
    return _resultado_error(personalidad, "Fallo critico en Groq")





async def _llamar_ollama(personalidad, prompt_analista, modelo="qwen2.5:14b"):
    try:
        import aiohttp

        prompt_modelo = _preparar_prompt_para_modelo(
            prompt_analista,
            max_chars=OLLAMA_PROMPT_MAX_CHARS,
        )
        url = "http://localhost:11434/api/generate"
        instruccion = PERSONALIDADES[personalidad]["instruccion"]
        payload = {
            "model": modelo,
            "prompt": (
                f"{instruccion}\n\n"
                "Responde unicamente con un JSON valido sin texto adicional.\n\n"
                f"{prompt_modelo}"
            ),
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
        }
        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(total=OLLAMA_TIMEOUT_SECONDS)
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    texto = data.get("response", "")
                    pick_json = _parsear_json_modelo(texto)
                    return _resultado_ok(personalidad, pick_json, texto, prompt_modelo)

                error = await resp.text()
                return _resultado_error(personalidad, "Ollama no disponible", error)
    except json.JSONDecodeError as e:
        return _resultado_error(personalidad, f"JSON invalido: {e}", locals().get("texto", ""))
    except asyncio.TimeoutError:
        return _resultado_error(
            personalidad,
            f"Ollama timeout tras {OLLAMA_TIMEOUT_SECONDS}s",
            locals().get("texto", ""),
        )
    except Exception as e:
        return _resultado_error(
            personalidad,
            f"Ollama no disponible: {e}",
            locals().get("texto", ""),
        )


def _construir_tareas(prompt_analista):
    google_key = os.getenv("GOOGLE_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")

    tareas = []
    if google_key:
        tareas.append(_llamar_gemini("Auto-Gemini-Contextual", prompt_analista, google_key))
    if groq_key:
        tareas.append(_llamar_groq("Auto-Groq-Contraste", prompt_analista, groq_key))
    
    tareas.append(_llamar_ollama("Auto-Ollama-Conservador", prompt_analista, "llama3.1:8b"))
    return tareas


async def _ejecutar_con_callback(prompt_analista, callback):
    tareas = _construir_tareas(prompt_analista)
    if not tareas:
        return [], "No hay API keys configuradas."

    pendientes = {asyncio.ensure_future(tarea): tarea for tarea in tareas}
    resultados = []

    for coro in asyncio.as_completed(list(pendientes.keys())):
        try:
            resultado = await coro
        except Exception as e:
            resultado = {"status": "error", "error": str(e), "ia": "desconocida"}
        resultados.append(resultado)
        if callback:
            callback(resultado)

    return resultados, None


def ejecutar_analisis_automatico(prompt_analista, callback=None):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        resultados, error = loop.run_until_complete(
            _ejecutar_con_callback(prompt_analista, callback)
        )
        loop.close()
        return resultados, error
    except Exception as e:
        return [], str(e)


def verificar_apis_configuradas():
    estado = {
        "Gemini (Google)": bool(os.getenv("GOOGLE_API_KEY")),
        "Groq": bool(os.getenv("GROQ_API_KEY")),
    }
    try:
        import requests

        respuesta = requests.get("http://localhost:11434/api/tags", timeout=2)
        estado["Ollama (local)"] = respuesta.status_code == 200
    except Exception:
        estado["Ollama (local)"] = False
    return estado
