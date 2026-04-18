# Continuidad de sesion

Ultima actualizacion: 2026-03-20
Base activa del proyecto:
- `C:\Users\corzo\OneDrive\Documentos\chat gpt codex\JrAI11_CLUADE_WORK - GIT\06_APP`

## Decision de ruta

Se dejo de trabajar sobre `JrAI11_CLUADE_WORK` y se paso a trabajar sobre:
- `JrAI11_CLUADE_WORK - GIT`

Motivo:
- el usuario confirmo que `- GIT` era una copia directa de la version previa con cambios adicionales hechos por el mismo;
- por eso se tomo esa ruta como linea principal de trabajo.

## Cambios principales hechos en esta sesion

### 1. Preparar Partido ahora usa seleccion por fecha local

Archivos:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)
- [match_prepare_service.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/services/match_prepare_service.py)

Se implemento:
- flujo principal por fecha local en lugar de depender solo del input manual;
- listado de partidos analizables por fecha;
- filtro para mostrar solo partidos no iniciados en hora local;
- posibilidad de ver tambien proximos dias;
- al seleccionar un partido se carga el fixture automaticamente.

Notas:
- el filtro de hora local se amarra a `America/Bogota`;
- la lista de partidos solo aparece en el paso de buscar fixture.

### 2. Se eliminaron llamadas duplicadas a la API

Archivo:
- [match_prepare_service.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/services/match_prepare_service.py)

Se corrigio:
- dentro de `preparar_partido_desde_api()` habia llamadas duplicadas solo para debug;
- esas llamadas extra fueron eliminadas;
- esto reduce consumo innecesario de requests de API-Football.

### 3. Se elimino la pestana Consulta de Cuotas

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

Se quito:
- pestana vieja de `Consulta de Cuotas`;
- flujo asociado que ya no aportaba al producto actual.

### 4. Reorganizacion de tabs principales

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

Se reorganizo la app para que el flujo principal quede mas claro.

Tabs principales:
- Dashboard
- Resultados
- Base y Publicacion
- Preparar Partido
- Analisis IA
- Motor Propio
- Usuarios

Tabs laboratorio:
- Lab Consenso
- Lab Aprendizaje
- Lab Comparativa

### 5. Aprendizaje fue reenfocado al Motor Propio

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

`Lab Aprendizaje` dejo de estar centrado en pesos de IAs y ahora lee el rendimiento del `Motor-Propio`.

Ahora muestra:
- picks del motor;
- cerrados / pendientes;
- acierto ponderado;
- ROI del motor;
- lectura por mercado;
- lectura por bandas de confianza;
- comparativa rapida `Motor vs resto`.

### 6. Motor Propio se volvio menos rigido y mas util

Archivo:
- [motor_picks.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/motor_picks.py)

Se ajusto:
- umbral de confianza operativo de `0.65` a `0.62`;
- se permitio `0.5u` en casos buenos pero no perfectos;
- el EV ahora aporta un pequeno boost a la confianza;
- se puede emitir pick con 4 apoyos si:
  - calidad del input es alta;
  - fit de mercado es fuerte;
  - EV es bueno;
  - penalizacion estructural es baja.

### 7. Guardrails contra picks locos de cuotas largas

Archivo:
- [motor_picks.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/motor_picks.py)

Se reforzo:
- deteccion de `favorito estructural`;
- castigo a `away win` o `moneylines` largos cuando el favorito estructural sigue siendo claro;
- ranking ahora usa `score_ajustado`, no solo EV bruto.

Objetivo:
- evitar picks descabellados aunque haya value superficial.

### 8. Se anadio senal real del arbitro al motor

Archivo:
- [motor_picks.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/motor_picks.py)

Se agrego:
- lectura de `promedio amarillas arbitro`;
- suma a la `calidad_input`;
- empuja suavemente fit de mercados como:
  - Over 2.5
  - Under 2.5
  - BTTS Si
  - BTTS No
- aparece en salida tecnica como:
  - `arbitro_tarjetas`

Importante:
- por ahora solo se usa `promedio amarillas arbitro`;
- no se modelan aun mercados de tarjetas como pick independiente.

### 9. Preparar Partido fue simplificado a 3 pasos reales

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

Antes:
- Buscar fixture
- Revisar API
- Completar manual
- Generar ficha

Ahora:
- Buscar fixture
- Completar manual
- Generar ficha

Motivo:
- `Revisar API` ya no aportaba como paso separado;
- lo util quedo integrado dentro de la mesa de trabajo manual.

### 10. Se limpio mucho la UI de Preparar Partido

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

Se cambio:
- la lista de partidos solo se muestra en el paso 1;
- la ficha tecnica consolidada ahora esta en un expander;
- el diagnostico tecnico de API esta en un expander tecnico;
- arriba solo queda:
  - que trajo la API;
  - que no trajo;
  - que falta completar manualmente.

### 11. Los faltantes de API ahora se reflejan como lista accionable

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

En `Campos que aun debes completar manualmente` ahora aparecen:
- campos manuales obligatorios:
  - xG local
  - xG visitante
  - ELO local
  - ELO visitante
  - promedio amarillas arbitro
  - motivacion/contexto local
  - motivacion/contexto visitante
  - contexto adicional
- y tambien faltantes reales de API:
  - lesiones local/visitante si faltan;
  - alineaciones local/visitante si faltan;
  - arbitro si faltara.

### 12. Se corrigio el problema de alineaciones falsas

Archivos:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)
- [match_prepare_service.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/services/match_prepare_service.py)

Problema:
- la API podia devolver objetos de lineup vacios;
- la UI a veces marcaba `Alineaciones = OK` aunque viniera `Formacion: None` y sin titulares.

Se corrigio:
- ahora se exige formacion valida o suficientes titulares utiles;
- si no, alineaciones se considera faltante;
- el texto ya no muestra `Formacion: None` como si fuera algo util;
- ahora muestra `Sin formacion confirmada`.

### 13. Contexto externo con Perplexity integrado

Archivo:
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

Se agrego en `Preparar Partido`:
- un `Prompt personalizado para Perplexity` generado segun el partido elegido;
- un campo `Resultado pegado desde Perplexity`;
- un boton:
  - `Usar respuesta de Perplexity como contexto base`

Ademas:
- ese texto de Perplexity entra al bloque de contexto que usa Ollama;
- se guarda en `manual_data` como `contexto_perplexity`.

Objetivo:
- Perplexity trae contexto reciente y verificable;
- Ollama lo transforma en motivacion/contexto util para el motor.

### 14. Logging total inicial del Motor Propio

Archivos:
- [database.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/database.py)
- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)

Se agrego:
- tabla nueva `motor_pick_logs`;
- guardado de cada corrida del motor, incluso cuando da `NO BET`;
- guardado adicional cuando un pick del motor se manda a la base principal;
- lectura minima en `Lab Aprendizaje` para ver:
  - corridas del motor
  - cuantos picks emitio
  - cuantos `NO BET` saco

Campos importantes del log:
- mercado
- seleccion
- cuota
- probabilidad_modelo
- probabilidad_implicita
- EV
- confianza
- calidad_input
- market_fit_score
- guardrail_penalty
- favorito_estructural
- contexto_perplexity
- snapshot de entrada
- sistemas
- candidatos
- decision
- riesgos

Objetivo:
- empezar la fase de trazabilidad completa del motor;
- poder aprender del motor de verdad y no solo de picks guardados.

## Estado actual del flujo Preparar Partido

Flujo vigente:
1. Elegir fecha local
2. Ver partidos no iniciados
3. Seleccionar partido
4. Ver resumen corto de API
5. Completar:
   - xG
   - ELO
   - promedio amarillas arbitro
   - motivacion/contexto
   - faltantes reales de API
6. Opcional:
   - usar prompt de Perplexity
   - pegar respuesta
   - pedir a Ollama que estructure ese contexto
7. Generar ficha
8. Pasar a `Motor Propio`

## Estado actual de la idea del producto

Decision principal:
- el sistema debe depender cada vez menos de IAs externas para decidir picks;
- `Motor Propio` es el decisor principal;
- `Analisis IA` queda mas como contraste o narrativa;
- `Perplexity` sirve como fuente manual/externa de contexto;
- `Ollama` sirve como estructurador local de contexto, no como investigador con internet.

## Archivos clave para continuar

- [app.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/app.py)
- [motor_picks.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/motor_picks.py)
- [services/match_prepare_service.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/services/match_prepare_service.py)
- [services/ollama_context_service.py](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/services/ollama_context_service.py)
- [AI_FEEDBACK](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/AI_FEEDBACK)
- [CONSOLIDATED_REVIEW_2026-03-20.md](/C:/Users/corzo/OneDrive/Documentos/chat%20gpt%20codex/JrAI11_CLUADE_WORK%20-%20GIT/06_APP/AI_FEEDBACK/CONSOLIDATED_REVIEW_2026-03-20.md)

## Recomendaciones para continuar en otra sesion o con otra IA

1. Seguir trabajando sobre:
   - `JrAI11_CLUADE_WORK - GIT`
2. No volver a la ruta vieja salvo para comparar.
3. Mantener `Motor Propio` como eje principal.
4. Si se sigue tocando `Preparar Partido`, priorizar:
   - menos ruido visual;
   - mas lista accionable de faltantes;
   - mejor integracion `Perplexity -> Ollama -> Motor`.
5. Si se piden auditorias a otras IAs sobre el motor:
   - guardar sus respuestas en `06_APP/AI_FEEDBACK/`;
   - preferir `.txt` por IA o por sesion;
   - luego leerlas y consolidar mejoras reales.
6. Ya existe una consolidacion inicial de auditorias externas:
   - `AI_FEEDBACK/CONSOLIDATED_REVIEW_2026-03-20.md`
   - usarla como base antes de volver a pedir auditorias nuevas.
7. Futuras mejoras probables:
   - usar mejor contexto de eliminatorias (ida/vuelta, marcador global);
   - seguir afinando el motor para reducir `NO BET` sin volverlo irresponsable;
   - si hace falta, extender seÃ±al del arbitro con rojas como dato secundario.

## Avance nuevo: aprendizaje operativo desde logs

Ya se inicio la fase correcta posterior a las auditorias externas:
- primero medir mejor el motor antes de volver a retocar fuerte sus umbrales.

Cambios hechos:
- se mantuvo el `logging total` del `Motor Propio`;
- `Lab Aprendizaje` ahora lee `motor_pick_logs` y no solo picks cerrados en la base;
- se anadieron nuevas lecturas:
  - `Pick rate`
  - `EV medio emitidos`
  - `Confianza media emitidos`
  - `Calidad input media`
- se anadio una tabla `Donde emite y donde se bloquea` por mercado;
- se anadio una tabla de `Bloqueos mas repetidos del motor`;
- se anadio una vista de `Sensibilidad por calidad del input`.

Objetivo de este avance:
- entender en que mercados el motor se frena mas;
- detectar si el exceso de `NO BET` viene por calidad, guardrails, confianza o fit de mercado;
- no seguir calibrando a ciegas.

## Avance nuevo: calibracion sugerida desde Lab Aprendizaje

Se anadio una capa de recomendaciones concretas dentro de `Lab Aprendizaje`.
Ya no solo diagnostica: ahora propone acciones de calibracion segun los logs.

La vista nueva sugiere ajustes cuando detecta:
- pick rate demasiado bajo o demasiado alto;
- calidad de input alta pero emision baja;
- bloqueos dominantes como `menos de 5 sistemas`, `confianza por debajo`, `calidad de input insuficiente` o `mercado sin confirmacion especifica`;
- mercados con buen perfil operativo;
- mercados atascados pese a EV alto.

Objetivo:
- convertir el aprendizaje del motor en decisiones practicas de tuning;
- dejar de calibrar solo por intuicion;
- preparar la siguiente fase: retocar umbrales por mercado con evidencia.

## Avance nuevo: se incorporo `CHAT GPT.txt` al consolidado

Aporte diferencial detectado:
- separar mejor forecast, decision, calibracion y staking;
- mejorar tratamiento de mercado en cuotas largas;
- considerar no-vig mas serio y mas adelante Shin/power;
- guardar y explotar mejor candidatos, no solo el pick final;
- preparar a futuro una capa de incertidumbre tipo `EV_lower_bound`.

Conclusión:
- no cambia la ruta principal actual;
- pero refuerza que la siguiente fase importante debe atacar calibracion por mercado y cuotas largas.

## Avance nuevo: calibracion inicial por mercado y cuota en el motor

Se anadio una primera capa real de calibracion en `motor_picks.py`.
No es solo otro guardrail al final: ahora la probabilidad del candidato puede encogerse hacia mercado antes de decidir.

Cambios clave:
- nueva logica de `shrinkage` por:
  - tipo de mercado;
  - bucket de cuota;
  - favorito estructural;
  - calidad del input.
- las cuotas altas y `longshots` reciben mas prudencia;
- los picks contra favorito estructural reciben castigo adicional;
- el ranking de candidatos ya usa:
  - `prob_calibrada`
  - `ev_calibrado`
  en vez de apoyarse solo en el valor bruto.
- se anadio `calibracion_mercado` a la salida tecnica del motor.
- se anadieron riesgos nuevos cuando la calibracion recorta fuerte una idea o cuando una cuota larga queda castigada.

Objetivo:
- bajar edge falso en cuotas largas;
- hacer menos probable que un underdog raro suba solo por EV bruto;
- preparar el camino para una calibracion empirica mas seria despues.

## Avance nuevo: calibracion semi-empirica con historial real

Se anadio una capa nueva en `motor_picks.py` que usa historial real de `Motor-Propio` ya cerrado.

Que hace:
- toma picks cerrados de `Motor-Propio` desde la base;
- agrupa por mercado y bucket de cuota;
- mide hit rate, probabilidad implicita media y ROI historico;
- aplica un ajuste empirico prudente sobre la probabilidad calibrada.

Efecto practico:
- si historicamente un tipo de pick sale mal en ese mercado/bucket, el motor lo castiga un poco mas;
- si historicamente responde bien y hay muestra suficiente, le suelta un poco la mano;
- ahora la tabla de candidatos muestra:
  - `Prob. calibrada`
  - `EV calibrado %`
  - `Shrink %`
  - `Empirico %`
  - `Muestra emp.`

Objetivo:
- dejar de calibrar solo por intuicion;
- empezar a castigar valor falso con memoria historica real;
- preparar una calibracion por mercado/cuota cada vez menos heuristica.

## Avance nuevo: fix de alineaciones API

Se reforzo el parser de `fixtures/lineups`.

Cambios:
- parser de titulares mas flexible;
- limpieza de `formation = None`;
- se guardan tambien suplentes como respaldo;
- en la UI se mejoro el emparejamiento local/visitante de lineups;
- si hay dos lineups pero el nombre no empata perfecto, se usa fallback por posicion para no perder alineaciones validas.

Objetivo:
- evitar falsos `Sin alineacion confirmada` cuando la API si trajo datos;
- reducir fallos por nombres de equipo o formato ligeramente distinto de la respuesta.

## Avance nuevo: prompts de Ollama mas exigentes para contexto

Se reforzo `services/ollama_context_service.py`.

Mejoras:
- ahora el prompt obliga a considerar:
  - si es liga o eliminatoria;
  - ida/vuelta o marcador global;
  - urgencia real;
  - racha;
  - bajas fuertes;
  - arquero debutante;
  - arbitro tarjetero;
  - cambios de ultimo momento.
- se prohibieron resumenes demasiado genericos;
- se anadio un ejemplo de buena salida;
- se fijo `temperature` baja para respuestas mas consistentes.

Objetivo:
- que Ollama deje de devolver contexto plano;
- y convierta mejor una buena respuesta de Perplexity en texto operativo para la app.

## Avance nuevo: fallback para prompt de Analisis IA

Se corrigio el flujo de `Analisis IA` cuando falta `01_PROMPTS/automatizacion/analista_prompt_automatico.txt`.

Cambios:
- `core/utils.py` ahora busca el prompt en varias rutas candidatas;
- si no existe archivo, usa un prompt interno de respaldo (`PROMPT_AUTOMATICO_FALLBACK`);
- `app.py` ya no rompe el flujo con `FileNotFoundError`.

Objetivo:
- que `Ejecutar analisis automatico` funcione aunque no exista esa carpeta vieja de prompts.

## Avance nuevo: fix del puente Preparar Partido -> Motor Propio

Se corrigio el traspaso de datos manuales entre ambas pestanas.

Problema detectado:
- xG, ELO y contexto escritos en `Preparar Partido` no siempre llegaban bien a `Motor Propio`;
- eso podia dejar el motor sin contexto aunque el usuario ya lo hubiera completado.

Solucion aplicada:
- nueva funcion `_collect_prepared_manual_bridge()` en `app.py`;
- `Motor Propio` ahora hereda desde:
  - `prepared_match_manual_data`
  - y, como respaldo, los widgets `prep_*` de sesion;
- al generar ficha se guarda tambien `contexto_libre` consolidado;
- al ejecutar el motor se preserva mejor el bloque manual completo en sesion.

Objetivo:
- evitar que el usuario tenga que reescribir xG, ELO o contexto al pasar de una pestana a otra.

## Avance nuevo: prompt fallback de Analisis IA alineado al validador

Se reforzo `PROMPT_AUTOMATICO_FALLBACK` en `core/utils.py`.

Problema detectado:
- varias IAs devolvian JSON valido pero demasiado simple;
- el validador de `ai_providers.py` exige `veredictos_sistemas` y `fundamentos_clave`;
- por eso se descartaban aunque el analisis base no fuera absurdo.

Solucion aplicada:
- el fallback ahora exige el esquema completo esperado por el validador;
- obliga a devolver las 8 claves de `veredictos_sistemas`;
- obliga a devolver al menos 3 `fundamentos_clave`;
- deja reglas explicitas para `PICK` y `NO BET`.

Objetivo:
- reducir descartes por formato;
- hacer que `Analisis IA` falle menos por contrato JSON y no por contenido.

## Avance nuevo: ajuste de fit para 1X2 y lectura de sistemas mas clara

Se mejoro `motor_picks.py` y `app.py`.

En el motor:
- el `market_fit_score` para `1X2` local/visitante ya no depende casi solo de lambda y tiros;
- ahora tambien toma en cuenta:
  - ELO alineado;
  - forma reciente alineada;
  - ventajas ligeras, no solo ventajas muy grandes.

Objetivo:
- evitar casos donde un visitante con 5 sistemas a favor quedaba con `fit = 0` por reglas demasiado duras.

En la UI:
- la tabla `Lectura por sistema` ahora muestra `-` en vez de `None`;
- se anadio una nota explicando que `-` significa `no aplica` para ese sistema, no necesariamente error.

## Avance nuevo: reset completo del bloque Perplexity en Preparar Partido

Se corrigio `_reset_prepared_widgets()` en `app.py`.

Problema:
- al cambiar de fixture, el prompt personalizado y la respuesta pegada de Perplexity podian quedarse del partido anterior.

Fix aplicado:
- ahora tambien se resetean:
  - `prep_prompt_perplexity`
  - `prep_perplexity_resultado`
  - `prep_arbitro_cards_avg`

Resultado esperado:
- al seleccionar un partido nuevo, `Preparar Partido` arranca limpio en esos campos y el prompt se regenera con el nuevo fixture.
