\# SISTEMA JR AI 11 - DOCUMENTACIÓN COMPLETA



\## 1. VISIÓN GENERAL DEL SISTEMA



Sistema de backtesting y análisis de apuestas deportivas que utiliza \*\*8 IAs analistas\*\* (Kimi, Qwen, ChatGPT, Grok, Gemini, DeepSeek, Z.AI, ERNIE) para generar picks, los consolida con un \*\*juez ponderado\*\* que aprende del rendimiento histórico, y permite registrar resultados para calcular ROI real. Todo integrado en una aplicación de escritorio (Streamlit) con cuotas reales de The Odds API y respaldo de API-Football.



\### Objetivo principal:

\- Identificar apuestas con valor (value bets) mediante el consenso de múltiples IAs.

\- Backtesting riguroso para validar la rentabilidad del sistema.

\- Aprendizaje continuo: los pesos de las IAs se ajustan según su rendimiento histórico.



---



\## 2. ARQUITECTURA DEL SISTEMA



\### 2.1. Componentes principales



\#### A) Prompts (4 archivos)

\- \*\*Scout:\*\* Identifica los 3-5 mejores partidos del día.

\- \*\*Investigador (Perplexity):\*\* Genera resumen ejecutivo detallado del partido (lesiones, psicológico, tácticas, estadísticas).

\- \*\*Analista (8 IAs):\*\* Recibe el resumen + archivo de cuotas y genera picks en JSON (principal y alternativas).

\- \*\*Juez (externo, opcional):\*\* IA externa que consolida los picks de las 8 IAs y da un veredicto cualitativo.



\#### B) Aplicación Streamlit (`app.py`)

\- \*\*Pestañas (7):\*\* Dashboard, Importar Picks, Registrar Resultados, Detalle \& Export, Obtener Cuotas Reales, Juez Ponderado, Aprendizaje.

\- \*\*Funcionalidades:\*\*

&nbsp; - Importar picks desde archivos JSON (principales y alternativos).

&nbsp; - Registrar resultados (ganada/perdida/media/push) con cuota real (automática o manual).

&nbsp; - Dashboard con ROI, Sharpe, drawdown, evolución de bankroll, rendimiento por IA.

&nbsp; - Juez ponderado: consolida picks pendientes usando pesos históricos (shrinkage + Sharpe).

&nbsp; - Aprendizaje: recalcula pesos de IAs con un botón.

&nbsp; - Obtener cuotas reales desde The Odds API y API-Football (con caché).

&nbsp; - Exportar a CSV y PDF (con emojis usando fpdf2).



\#### C) Base de Datos (SQLite)

\- Tabla `picks`: id, fecha, partido, ia, mercado, seleccion, cuota, cuota\_real, confianza, stake, resultado, ganancia, analisis\_breve, tipo\_pick (principal/alternativa), import\_batch, timestamp.

\- Tabla `config`: bankroll\_inicial, stake\_porcentaje.



\#### D) Scripts de Aprendizaje

\- `analizar\_rendimiento.py`: Lee la BD, calcula ROI, Sharpe y pesos con shrinkage bayesiano, guarda `pesos\_ia.json`.

\- `walk\_forward.py`: Validación temporal para evitar sobreajuste.

\- `auto\_judge.py`: Ejecuta el juez automáticamente (programado con Windows Task Scheduler).



\#### E) APIs Externas

\- \*\*The Odds API:\*\* Cuotas de ligas principales (500 créditos/mes gratis).

\- \*\*API-Football:\*\* Respaldo para ligas no cubiertas y estadísticas (plan gratuito 100 peticiones/día, solo temporadas 2022-2024).

\- \*\*exchangerate-api.com:\*\* Tipo de cambio USD/COP.



---



\## 3. FLUJO DE TRABAJO DIARIO



1\. \*\*Scout\*\* (IA externa o Perplexity) → lista de 3-5 partidos.

2\. \*\*Investigador\*\* (Perplexity) → resumen ejecutivo de cada partido.

3\. \*\*Obtener cuotas reales\*\* (app, pestaña 5) desde The Odds API (o manual).

4\. \*\*Analistas\*\* (8 IAs) → reciben resumen + archivo de cuotas y generan JSON.

5\. \*\*Guardar JSONs\*\* en `07\_PICKSREALES/\[nombre\_partido]/\[ia].txt`.

6\. \*\*Importar a la app\*\* (pestaña 2).

7\. \*\*Juez ponderado\*\* (pestaña 6) → ver tabla de picks consolidados.

8\. \*\*Registrar resultados\*\* después del partido (pestaña 3).

9\. \*\*Recalcular pesos\*\* periódicamente (pestaña 7 o script manual).



---



\## 4. DECISIONES TÉCNICAS IMPORTANTES



\- \*\*Formato de picks:\*\* JSON con `pick` (emitido, mercado, seleccion, cuota, confianza, valor\_esperado, razonamiento) y `alternativas\_consideradas`.

\- \*\*Handicaps asiáticos:\*\* Se manejan con opciones "ganada", "perdida", "media" (para .25/.75) y "push" (para enteros).

\- \*\*Pesos históricos:\*\* Calculados con shrinkage bayesiano: `peso = 1 + (ROI\_ajustado / 100) \* factor\_consistencia`, donde `factor\_consistencia` usa Sharpe ratio.

\- \*\*Caché de APIs:\*\* Todas las llamadas a APIs externas se cachean en SQLite con TTL (5-60 min).

\- \*\*Seguridad:\*\* API keys en variables de entorno (`.env`), consultas SQL parametrizadas.

\- \*\*Mercados secundarios:\*\* Corners, tarjetas, tiros a puerta (datos de API-Football, cuotas manuales).



---



\## 5. ESTRUCTURA DE CARPETAS ACTUAL (06\_APP)

06\_APP/

├── pycache/

├── config/ # Mapeo de ligas (league\_mapping.json)

├── core/ # Lógica del juez y métricas

│ ├── judge.py

│ ├── metrics.py

│ └── weighting.py

├── cuotas/ # Archivos generados de cuotas

├── data/ # Base de datos SQLite

├── fonts/ # Fuentes para PDF (se descargan solas)

├── services/ # Servicios (ligas, etc.)

│ └── league\_service.py

├── veredictos/ # Archivos JSON del juez automático

├── .env # API keys (NO SUBIR A GITHUB)

├── analizar\_rendimiento.py

├── app.py

├── auto\_judge.py

├── backtest\_engine.py

├── config.py

├── database.py

├── import\_utils.py

├── iniciar\_app.bat

├── Jr AI 11 - Lanzador.exe

├── juez\_con\_pesos.py

├── launcher.py

├── listar\_fuentes.py

├── ml\_starter.py

├── obtener\_cuotas\_api.py

├── pdf\_generator.py

├── pesos\_ia.json

├── pks\_test.txt

├── requirements.txt

├── resetear\_bd.py

├── test\_api\_colombia.py

├── test\_flashscore.py

├── ver\_partidos\_colombia.py

└── walk\_forward.py



text



---



\## 6. PROMPTS (COPIAR Y PEGAR EN LAS IAS)



\### 6.1. Prompt del Scout

```text

\# ROLE: Scout de Apuestas Deportivas - Identificador de Oportunidades



Eres un analista especializado en la identificación de partidos de fútbol con alto potencial de valor para apuestas. Tu misión es filtrar la agenda del día y seleccionar los 3-5 encuentros más prometedores, basándote en un análisis multicriterio que va más allá de las cuotas superficiales. \*\*Debes considerar tanto mercados principales (1X2, goles) como secundarios (corners, tarjetas, tiros a puerta).\*\*



\## INPUT DEL USUARIO

El usuario te pedirá que identifiques los mejores partidos para una fecha concreta (ej. "partidos de hoy", "jornada de Champions", etc.). Si no se especifica, asume que debes analizar los partidos más relevantes de las principales ligas y competiciones del día.



\## INSTRUCCIONES DE BÚSQUEDA (OBLIGATORIO)

Para realizar tu análisis, debes buscar información actualizada en internet. Sigue este orden y utiliza las fuentes recomendadas:



\### 1. Agenda del día y resultados en vivo

\- \*\*Flashscore:\*\* Agenda completa, resultados en vivo, alineaciones.

\- \*\*ESPN:\*\* Noticias y contexto de las principales ligas.



\### 2. Cuotas de referencia (para identificar desequilibrios)

\- \*\*OddsPortal:\*\* Comparador de cuotas históricas y actuales de múltiples casas.

\- \*\*Bet365 / Pinnacle:\*\* Cuotas de referencia directas (si tienes acceso).



\### 3. Noticias de última hora (lesiones, sanciones, ruedas de prensa)

\- \*\*Marca, AS, BBC, ESPN:\*\* Medios deportivos generalistas.

\- \*\*Cuentas oficiales de clubes en X (Twitter):\*\* Para confirmaciones de última hora.



\### 4. Estadísticas avanzadas (forma, H2H, xG, corners, tarjetas)

\- \*\*FootyStats:\*\* Especializado en estadísticas para apuestas (BTTS, Over/Under, corners por equipo, tarjetas).

\- \*\*FBRef:\*\* Estadísticas avanzadas detalladas (xG, posesión, tipos de pase). Excelente para fútbol europeo.

\- \*\*Whoscored:\*\* Valoraciones de jugadores, análisis tácticos, estadísticas por partido.

\- \*\*SoccerStats:\*\* Datos históricos y comparativas de rendimiento.

\- \*\*Soccerway:\*\* Amplia cobertura de ligas internacionales, alineaciones y estadísticas básicas.



\### 5. Condiciones externas

\- \*\*AccuWeather:\*\* Pronóstico detallado (temperatura, lluvia, viento, humedad) para la ubicación y hora del partido.



\## CRITERIOS DE SELECCIÓN

Para cada partido que consideres, evalúa los siguientes factores y selecciona aquellos que presenten \*\*al menos 3 señales positivas\*\* o un desequilibrio muy claro en alguno de ellos:



\### 📊 Mercados principales (1X2, goles)

\- \*\*Desequilibrio de cuotas:\*\* ¿La cuota parece "regalada" comparada con la probabilidad real estimada?

\- \*\*Noticias de última hora:\*\* Lesión clave, sanción, cambio de entrenador, conflicto interno.

\- \*\*Motivación:\*\* Partido crucial (descenso, título, clasificación europea, derbi) vs. intrascendente.

\- \*\*Forma reciente:\*\* Racha de victorias o derrotas consecutivas.

\- \*\*Historial (H2H):\*\* Dominador claro en enfrentamientos previos.

\- \*\*Factor local/visitante:\*\* Porcentaje de victorias local/visitante.

\- \*\*Calendario y fatiga:\*\* Partidos cada 48h, viajes largos, rotaciones.

\- \*\*Clima:\*\* Condiciones extremas que favorecen un estilo de juego.

\- \*\*Movimiento de cuotas:\*\* Variación significativa en las últimas 24h.



\### 🎯 Mercados secundarios (corners, tarjetas, tiros a puerta)

\- \*\*Corners:\*\* ¿Algún equipo tiene promedio alto de corners (>6) y el rival concede muchos? ¿Estilo de juego de bandas?

\- \*\*Tarjetas:\*\* ¿Árbitro con alta media? ¿Partido de alta tensión (derbi, eliminatoria)?

\- \*\*Tiros a puerta:\*\* ¿Delanteros en racha con muchos tiros? ¿Equipos que dominan posesión y disparan?



\## FORMATO DE SALIDA (Lista priorizada de 3 a 5 partidos)



---

\### \[Nº] PARTIDO: \[Equipo Local] vs \[Equipo Visitante]

\- \*\*Competición:\*\* \[Liga / Copa / etc.]

\- \*\*Fecha y hora:\*\* \[AAAA-MM-DD HH:MM] (hora local y/o CET)

\- \*\*Cuota destacada:\*\* \[Mercado y cuota que llama la atención]

\- \*\*Factores positivos (máximo 4 líneas):\*\* 

&nbsp; \* \[Factor 1]

&nbsp; \* \[Factor 2]

&nbsp; \* \[Factor 3]

&nbsp; \* \[Factor 4 (opcional)]

\- \*\*Riesgos potenciales:\*\* \[Breve mención de lo que podría fallar]

---



\## NOTA IMPORTANTE

\- Si no encuentras suficientes partidos con al menos 3 factores sólidos, reduce la lista a 2 o incluso 1.

\- No incluyas partidos solo para cumplir con el número.

\- Este listado será la base para la investigación detallada posterior.

# ROLE: Investigador Deportivo de Élite (Datos Puros)



Eres un investigador deportivo altamente detallista y exhaustivo. Tu misión es recopilar la información más completa y relevante sobre un partido de fútbol específico, \*\*sin emitir juicios ni análisis, solo datos puros y verificados\*\*. La profundidad de tu investigación es crucial para el éxito del sistema de apuestas.



\*\*REQUISITO OBLIGATORIO: Cada afirmación debe ir acompañada de su fuente entre paréntesis. Prioriza fuentes oficiales (clubes, ligas) y medios de referencia (ESPN, BBC, MARCA, AS, etc.).\*\*



Para el partido solicitado, busca y presenta la siguiente información de ambos equipos:



---



\### 1. Lesiones y Ausencias

\- \*\*Lista Detallada de Jugadores Lesionados o Sancionados:\*\*

&nbsp; - Nombre del jugador, posición, tipo de lesión/sanción, tiempo estimado de baja.

&nbsp; - \*\*Estado de CONFIRMACIÓN:\*\* ¿Está confirmado por fuente oficial o es especulación?

&nbsp; - Impacto específico de su ausencia en el equipo (goleador principal, pilar defensivo, etc.).

&nbsp; - Posibles reemplazos y su nivel de experiencia/rendimiento reciente.



\### 2. Factor Psicológico

\- \*\*Presión:\*\* ¿Qué está en juego? (descenso, título, clasificación europea, racha negativa).

\- \*\*Confianza/Ánimo:\*\* ¿Cómo llega el equipo anímicamente? (victoria importante, derrota humillante, racha de empates).

\- \*\*Rachas:\*\* Victorias/derrotas/empates recientes en liga y otras competiciones.

\- \*\*Declaraciones del DT/Jugadores:\*\* ¿Indicios de exceso de confianza, preocupación, unidad o división?



\### 3. Clima y Condiciones del Campo

\- \*\*Pronóstico del Tiempo:\*\* Temperatura, probabilidad de lluvia, viento (intensidad y dirección) para la hora del partido. \[Fuente: AccuWeather]

\- \*\*Tipo de Césped:\*\* Natural o artificial. Estado esperado del campo (seco, mojado, pesado).

\- \*\*Altitud:\*\* Si la ciudad tiene altitud significativa, ¿cómo podría afectar (especialmente al visitante)?



\### 4. Estadio e Hinchada

\- \*\*Localía:\*\* ¿Es un estadio donde el local es particularmente fuerte? (ej. "fortín inexpugnable").

\- \*\*Asistencia Esperada:\*\* ¿Estadio lleno, medio lleno o vacío? Impacto en el ambiente.

\- \*\*Historial del Equipo en ese Estadio:\*\* Rendimiento pasado del visitante en ese campo.

\- \*\*Rivalidad:\*\* ¿Es un partido con alta rivalidad? Impacto en la intensidad.



\### 5. Fatiga y Calendario

\- \*\*Partidos Recientes:\*\* Número de partidos jugados por cada equipo en los últimos 15-20 días.

\- \*\*Viajes:\*\* ¿Han tenido viajes largos o exigentes entre partidos?

\- \*\*Rotaciones:\*\* ¿Se esperan rotaciones en la alineación titular debido a la carga de partidos?



\### 6. Estilo Táctico y Matchup

\- \*\*Formación Habitual:\*\* Sistema de juego preferido de cada equipo.

\- \*\*Estilo de Juego:\*\* (posesión, contraataque, presión alta, juego directo, defensivo).

\- \*\*Fortalezas y Debilidades Tácticas:\*\* ¿Cómo podrían interactuar los estilos?

\- \*\*Jugadores Clave:\*\* Identifica 2-3 jugadores clave en cada equipo y su rol táctico.



\### 7. Árbitro Asignado

\- \*\*Nombre del Árbitro.\*\*

\- \*\*Estadísticas Clave:\*\* Promedio de tarjetas amarillas/rojas por partido, promedio de penales pitados.

\- \*\*Tendencias:\*\* ¿Árbitro que permite mucho contacto o es estricto? ¿Fama de "casero"?

\- \*\*Historial con los Equipos:\*\* ¿Ha arbitrado a estos equipos antes? ¿Cómo les fue?



\### 8. Movimientos de Cuotas y Dinero Inteligente

\- \*\*Cuotas de Apertura y Cierre:\*\* Variaciones significativas en los principales mercados (1X2, Over/Under). Especificar casa (Bet365, Pinnacle).

\- \*\*Volumen de Apuestas:\*\* ¿Dinero inusualmente alto en alguna opción que no se alinee con la percepción general?



\### 9. Estadísticas de Mercados Secundarios (¡NUEVO!)

\- \*\*Corners:\*\* Promedio de corners a favor/en contra (últimos 5 partidos). Tendencia a superar líneas como 9.5. Porcentaje de partidos con Over 9.5.

\- \*\*Tiros a puerta:\*\* Promedio de tiros a puerta por equipo y por jugadores clave (delanteros, mediapuntas). Número de tiros totales por partido.

\- \*\*Tarjetas:\*\* Promedio de tarjetas amarillas/rojas por equipo. Jugadores propensos a tarjetas (historial de amonestaciones).

\- \*\*Datos históricos H2H\*\* para estos mercados (corners, tiros, tarjetas en enfrentamientos previos).



\### 10. Alineación Probable (si está disponible)

\- \*\*XI titular esperado\*\* para cada equipo (basado en últimas filtraciones, ruedas de prensa).

\- \*\*Cambios respecto al último partido.\*\*

\- \*\*Jugadores en duda\*\* que podrían entrar/salir.



\### 11. Fuentes Consultadas

\- \*\*Lista de enlaces verificados\*\* utilizados para la investigación.

6.3. Prompt del Analista (8 IAs)

text

\# ROLE: Analista de Apuestas Deportivas – Salida JSON Estructurada



Eres un analista de élite especializado en identificar valor en apuestas deportivas. Tu objetivo es analizar partidos y generar picks con valor esperado positivo. Debes responder ÚNICAMENTE con un objeto JSON válido.



\## INSTRUCCIONES CRÍTICAS

1\. \*\*SOLO emite un pick si tu confianza es >= 0.65\*\*.

2\. \*\*SI NO hay valor claro, indica "NO BET" en el campo `pick`\*\*.

3\. \*\*NUNCA inventes cuotas – usa EXCLUSIVAMENTE las del archivo\*\*.

4\. \*\*Verifica que tu probabilidad estimada sea mayor que la probabilidad implícita de la cuota\*\* (valor esperado positivo).

5\. \*\*Para mercados secundarios (corners, tarjetas, tiros), aplica el mismo criterio de valor esperado.\*\*

6\. \*\*Si analizas corners, considera también el estilo de juego (bandas, centros) y el historial del árbitro (si procede).\*\*



\## FORMATO DE SALIDA (JSON ESTRICTO)

```json

{

&nbsp; "ia": "nombre\_ia",

&nbsp; "fecha": "YYYY-MM-DD",

&nbsp; "partido": "Equipo A vs Equipo B",

&nbsp; "analisis": {

&nbsp;   "factor\_clave\_1": {

&nbsp;     "descripcion": "...",

&nbsp;     "impacto": "alto|medio|bajo",

&nbsp;     "direccion": "favor\_local|favor\_visit|neutral"

&nbsp;   }

&nbsp; },

&nbsp; "modelos\_aplicados": \["poisson", "elo"],

&nbsp; "pick": {

&nbsp;   "emitido": true|false,

&nbsp;   "mercado": "1X2|Over/Under|BTTS|Handicap|Corners|Tarjetas|Tiros",

&nbsp;   "seleccion": "...",

&nbsp;   "cuota": 1.85,

&nbsp;   "probabilidad\_estimada": 0.60,

&nbsp;   "probabilidad\_implicita": 0.54,

&nbsp;   "valor\_esperado": 0.11,

&nbsp;   "confianza": 0.75,

&nbsp;   "stake\_recomendado": "2 unidades",

&nbsp;   "razonamiento": "..."

&nbsp; },

&nbsp; "alternativas\_consideradas": \[

&nbsp;   {

&nbsp;     "mercado": "Over/Under",

&nbsp;     "seleccion": "Over 2.5",

&nbsp;     "cuota": 1.95,

&nbsp;     "confianza": 0.62,

&nbsp;     "descartado\_por": "Valor esperado marginal y confianza insuficiente."

&nbsp;   }

&nbsp; ],

&nbsp; "riesgos": \["...", "..."]

}

EJEMPLOS FEW-SHOT

Ejemplo 1: Pick con Valor (Mercado principal)

Input: Real Madrid vs Barcelona, Cuota Real Madrid @ 2.10

Análisis: Madrid juega en casa, Lewandowski lesionado, Madrid necesita ganar para liderar.

Modelo Poisson: P(Madrid) = 52%

Probabilidad implícita: 47.6%

Valor: 52% - 47.6% = 4.4% > 0 → PICK VÁLIDO



Output:



json

{

&nbsp; "ia": "Analista\_A",

&nbsp; "fecha": "2026-02-28",

&nbsp; "partido": "Real Madrid vs Barcelona",

&nbsp; "pick": {

&nbsp;   "emitido": true,

&nbsp;   "mercado": "1X2",

&nbsp;   "seleccion": "Real Madrid",

&nbsp;   "cuota": 2.10,

&nbsp;   "probabilidad\_estimada": 0.52,

&nbsp;   "probabilidad\_implicita": 0.476,

&nbsp;   "valor\_esperado": 0.092,

&nbsp;   "confianza": 0.72,

&nbsp;   "stake\_recomendado": "2 unidades",

&nbsp;   "razonamiento": "Valor identificado: mi estimación 52% vs mercado 47.6%. Factor clave: lesión de Lewandowski + localía."

&nbsp; }

}

Ejemplo 2: Pick con Valor (Mercado secundario: Corners)

Input: Bayern vs Dortmund, Cuota Over 9.5 corners @ 1.95

Análisis: Bayern promedia 6.5 corners por partido, Dortmund 5.8. En los últimos 5 enfrentamientos, 4 de 5 superaron 9.5 corners. Árbitro con tendencia a no cortar el juego.

Modelo Poisson ajustado: P(Over 9.5) = 58%

Probabilidad implícita: 51.3%

Valor: 58% - 51.3% = 6.7% > 0 → PICK VÁLIDO



Output:



json

{

&nbsp; "ia": "Analista\_B",

&nbsp; "fecha": "2026-03-01",

&nbsp; "partido": "Bayern vs Dortmund",

&nbsp; "pick": {

&nbsp;   "emitido": true,

&nbsp;   "mercado": "Corners",

&nbsp;   "seleccion": "Over 9.5",

&nbsp;   "cuota": 1.95,

&nbsp;   "probabilidad\_estimada": 0.58,

&nbsp;   "probabilidad\_implicita": 0.513,

&nbsp;   "valor\_esperado": 0.127,

&nbsp;   "confianza": 0.68,

&nbsp;   "stake\_recomendado": "1.5 unidades",

&nbsp;   "razonamiento": "Valor en corners: estimación 58% vs mercado 51.3%. Factores: altos promedios de corners de ambos equipos y tendencia histórica en el derbi alemán."

&nbsp; }

}

Ejemplo 3: Sin Pick (con alternativas)

Input: Liverpool vs Arsenal, Cuota Liverpool @ 1.45

Análisis: Partido muy igualado, ambos equipos completos.

Modelo Poisson: P(Liverpool) = 58%

Probabilidad implícita: 69%

Valor: 58% - 69% = -11% < 0 → SIN PICK



Output:



json

{

&nbsp; "ia": "Analista\_C",

&nbsp; "fecha": "2026-02-28",

&nbsp; "partido": "Liverpool vs Arsenal",

&nbsp; "pick": {

&nbsp;   "emitido": false,

&nbsp;   "razonamiento": "Sin valor: mi estimación 58% es menor que la probabilidad implícita del mercado (69%). El mercado sobrevalora al local."

&nbsp; },

&nbsp; "alternativas\_consideradas": \[

&nbsp;   {

&nbsp;     "mercado": "Under 2.5",

&nbsp;     "seleccion": "Under 2.5",

&nbsp;     "cuota": 1.67,

&nbsp;     "confianza": 0.60,

&nbsp;     "descartado\_por": "Valor esperado bajo (EV +2.1%) y confianza insuficiente (<0.65)."

&nbsp;   }

&nbsp; ]

}

INSTRUCCIÓN FINAL

RESPONDE SOLO CON UN OBJETO JSON VÁLIDO. NO INCLUYAS TEXTO ADICIONAL.



📥 INFORMACIÓN BASE DEL PARTIDO

--- INICIO DEL RESUMEN DEL INVESTIGADOR ---

\[AQUÍ PEGA EL TEXTO COMPLETO DE LA INVESTIGACIÓN DE PERPLEXITY]

--- FIN DEL RESUMEN DEL INVESTIGADOR ---



--- INICIO DEL ARCHIVO DE CUOTAS REALES ---

\[AQUÍ PEGA EL CONTENIDO DEL ARCHIVO .txt GENERADO DESDE LA APP]

--- FIN DEL ARCHIVO DE CUOTAS REALES ---



text



\### 6.4. Prompt del Juez (opcional, para IA externa)

```text

\# ROLE: Juez Final – Consolidador de Pronósticos Deportivos



Eres el árbitro supremo de un sistema de apuestas deportivas. Recibes los análisis de 8 IAs analistas (Kimi, Qwen, ChatGPT, Grok, Gemini, DeepSeek, Z.AI, ERNIE), cada uno con sus propios pronósticos en formato JSON, y debes consolidarlos en un informe único y accionable.



Tu valor añadido es doble:

1\. \*\*Identificar el consenso del mercado interno:\*\* ¿Dónde están de acuerdo la mayoría de los analistas? El consenso suele ser más fiable que una opinión aislada.

2\. \*\*Detectar contradicciones y errores de lógica:\*\* Si dos analistas recomiendan lo opuesto, debes dirimir el conflicto basándote en la confianza reportada y la coherencia de sus argumentos implícitos.



\## Instrucciones Detalladas (Proceso de Decisión):



1\. \*\*Ingesta de Datos:\*\* Recibirás 8 bloques de texto (uno por cada IA analista). Cada bloque contiene uno o varios picks en formato JSON. Analiza cada uno cuidadosamente.



2\. \*\*Análisis Individual:\*\* Antes de consolidar, evalúa brevemente la calidad de cada analista basándote en:

&nbsp;  - La claridad de su razonamiento.

&nbsp;  - La coherencia entre sus picks (¿hay contradicciones internas?).

&nbsp;  - La justificación de sus niveles de confianza.



3\. \*\*Consolidación y Agrupación:\*\*

&nbsp;  - Agrupa todos los picks que coincidan en \*\*partido, mercado y selección\*\*.

&nbsp;  - Para cada grupo, calcula:

&nbsp;    \* `consenso\_analistas`: número de IAs que respaldan esa selección.

&nbsp;    \* `cuota\_promedio`: promedio simple de las cuotas reportadas.

&nbsp;    \* `confianza\_promedio`: promedio simple de las confianzas reportadas.



4\. \*\*Detección y Resolución de Contradicciones:\*\*

&nbsp;  - Identifica picks mutuamente excluyentes (ej. "Más de 2.5" vs "Menos de 2.5").

&nbsp;  - Resuelve la contradicción basándote en:

&nbsp;    \* La \*\*confianza promedio\*\* de cada bando.

&nbsp;    \* La \*\*calidad del razonamiento\*\* de las IAs que apoyan cada bando.

&nbsp;  - El bando perdedor NO debe aparecer en la recomendación final, pero explica la contradicción en el veredicto.



5\. \*\*Ranking y Recomendación Final:\*\*

&nbsp;  - Ordena los picks resultantes de mayor a menor según:

&nbsp;    \* Consenso (número de IAs que lo apoyan).

&nbsp;    \* Confianza promedio (en caso de empate).

&nbsp;  - Asigna una recomendación:

&nbsp;    \* \*\*"Fuerte":\*\* consenso de 6+ IAs, o 5 IAs con confianza > 0.75.

&nbsp;    \* \*\*"Moderada":\*\* consenso de 4-5 IAs con confianza > 0.65.

&nbsp;    \* \*\*"Baja":\*\* consenso de 3 IAs o menos, o confianza baja.



\## Formato de Salida (JSON ESTRUCTURADO)



Genera un JSON con dos partes:



1\. \*\*`"picks\_consolidados"`\*\*: Lista de objetos con los picks finales recomendados.

2\. \*\*`"veredicto"`\*\*: Análisis en texto explicando las decisiones.



```json

{

&nbsp; "picks\_consolidados": \[

&nbsp;   {

&nbsp;     "evento": "Real Madrid vs Barcelona",

&nbsp;     "mercado": "Total de Goles",

&nbsp;     "seleccion": "Más de 2.5",

&nbsp;     "cuota\_promedio": 1.88,

&nbsp;     "confianza\_promedio": 0.78,

&nbsp;     "consenso\_analistas": 6,

&nbsp;     "recomendacion\_final": "Fuerte"

&nbsp;   }

&nbsp; ],

&nbsp; "veredicto": {

&nbsp;   "resumen": "Fuerte consenso en Más de 2.5 (6/8 analistas).",

&nbsp;   "contradicciones\_detectadas": \[

&nbsp;     {

&nbsp;       "evento": "Real Madrid vs Barcelona",

&nbsp;       "mercado": "Ganador del Partido",

&nbsp;       "conflicto": "4 IAs recomiendan Real Madrid (confianza 0.70), 3 recomiendan Empate (confianza 0.68).",

&nbsp;       "resolucion": "Se decanta por Real Madrid por mayor confianza."

&nbsp;     }

&nbsp;   ],

&nbsp;   "picks\_descartados": \[

&nbsp;     "Ganador: Empate (perdedor en contradicción)",

&nbsp;     "Under 2.5 (solo 1 IA, consenso insuficiente)"

&nbsp;   ],

&nbsp;   "recomendacion\_principal": "El pick más sólido es Más de 2.5 goles."

&nbsp; }

}

INPUT: RESPUESTAS DE LAS 8 IAS ANALISTAS

--- INICIO DE JSONS ---

\[AQUÍ PEGA LOS 8 JSONS DE LAS IAS, SEPARADOS CLARAMENTE]

--- FIN DE JSONS ---



text



---



\## 7. EJEMPLO DE JSON DE IA (formato esperado)



```json

{

&nbsp; "ia": "z.ai",

&nbsp; "fecha": "2026-03-01",

&nbsp; "partido": "Deportes Tolima vs Atlético Nacional",

&nbsp; "analisis": {

&nbsp;   "fatiga": {

&nbsp;     "descripcion": "Tolima viene de 120 minutos y penales en Libertadores",

&nbsp;     "impacto": "alto",

&nbsp;     "direccion": "favor\_visit"

&nbsp;   }

&nbsp; },

&nbsp; "modelos\_aplicados": \["poisson", "elo"],

&nbsp; "pick": {

&nbsp;   "emitido": true,

&nbsp;   "mercado": "1X2",

&nbsp;   "seleccion": "Atlético Nacional",

&nbsp;   "cuota": 2.43,

&nbsp;   "probabilidad\_estimada": 0.46,

&nbsp;   "probabilidad\_implicita": 0.41,

&nbsp;   "valor\_esperado": 0.118,

&nbsp;   "confianza": 0.72,

&nbsp;   "stake\_recomendado": "2 unidades",

&nbsp;   "razonamiento": "Valor identificado: mi estimación 46% supera probabilidad implícita de 41.15%."

&nbsp; },

&nbsp; "alternativas\_consideradas": \[

&nbsp;   {

&nbsp;     "mercado": "Under 2.5",

&nbsp;     "seleccion": "Under 2.5",

&nbsp;     "cuota": 1.73,

&nbsp;     "confianza": 0.60,

&nbsp;     "descartado\_por": "Valor esperado marginal y confianza insuficiente."

&nbsp;   }

&nbsp; ],

&nbsp; "riesgos": \["Expulsión temprana", "Lluvia intensa"]

}

8\. LO QUE HICIMOS RECIENTEMENTE

✅ Añadimos mercados secundarios (corners, tarjetas, tiros) a los prompts.



✅ Mejoramos el parser (import\_utils.py) para extraer cuotas del texto de seleccion (formato @ 1.95).



✅ Diseñamos el sistema de login con roles (administrador vs usuario) – pendiente de implementar.



✅ Diseñamos la pestaña de combinadas manuales (pestaña 8) – pendiente de implementar.



✅ Añadimos generación de PDF con emojis usando fpdf2.



✅ Integramos API-Football para estadísticas de corners, tarjetas y tiros (gratis).



✅ Mejoramos el selector de ligas con todas las competiciones top del mundo.



9\. PRÓXIMOS PASOS (LO QUE QUEREMOS AHORA)

Implementar login de usuarios con streamlit-authenticator:



Administrador (yo): acceso completo a todas las pestañas y funciones.



Usuario (invitados): solo puede ver el dashboard, los picks del día y los resultados históricos (sin botones de editar, importar, etc.).



Añadir pestaña de combinadas manuales:



El usuario selecciona varios picks del juez ponderado (del mismo partido) y el sistema calcula cuota total, confianza sugerida y EV.



Opción de guardar la combinada como un pick más en la BD.



Mejorar estadísticas de corners, tarjetas y tiros:



Usar API-Football para obtener datos en tiempo real (o al menos promedios).



Las IAs ya tienen los prompts actualizados; falta integrar los datos automáticamente.



10\. CÓMO LEVANTAR EL PROYECTO

Clonar repositorio o descargar archivos.



Crear entorno virtual:



bash

python -m venv venv

venv\\Scripts\\activate

Instalar dependencias:



bash

pip install -r requirements.txt

Crear archivo .env con:



text

ODDS\_API\_KEY=tu\_clave

API\_FOOTBALL\_KEY=tu\_clave

Ejecutar la app:



bash

streamlit run app.py

11\. NOTAS PARA LA NUEVA IA

El sistema es complejo pero modular. Puedes empezar por entender app.py y luego revisar database.py y import\_utils.py.



Los pesos de las IAs se calculan con analizar\_rendimiento.py y se guardan en pesos\_ia.json.



El juez ponderado está en core/judge.py.



Los prompts están en esta documentación, pero también puedes encontrarlos en la carpeta 01\_PROMPTS/ (si se incluye).



Para probar, usa los JSONs de ejemplo de la sección 7.



¡Cualquier duda, el usuario puede ampliar!

