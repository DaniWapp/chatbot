# Flujo de una pregunta en el chat en vivo (streaming)

Este documento describe, paso a paso, qué pasa desde que un estudiante
escribe una pregunta en el widget de chat hasta que recibe la respuesta
completa. Sirve como referencia de arquitectura -- no implica ningún cambio
de código.

Ejemplo real usado para verificar cada paso: la pregunta "Ingeniería de
sistemas", medida contra la base de datos local (`chat_metrics`, `turns`,
`groq_calls`).

## 1. Navegador -- `frontend/script.js`

- El estudiante envía el formulario → `sendMessage(text)`.
- Se pinta de inmediato su burbuja (`addUserMessage`) y una burbuja de
  "escribiendo..." (`addAssistantPlaceholder`).
- Se hace `fetch("/api/chat/stream", {POST, body: {session_id, message}})`.

## 2. Entrada al backend -- `app/api/routes.py::chat_stream`

- Verifica que `GROQ_API_KEY` esté configurada (si no, responde 503 de
  inmediato, sin llegar a Groq).
- Envuelve `chat_service.stream_answer(session_id, mensaje)` en un
  generador y devuelve un `StreamingResponse` (Server-Sent Events, no un
  JSON único).

## 3. Núcleo del pipeline -- `app/services/chat_service.py::stream_answer`

1. Revisa `history_service.needs_human(session_id)`. Si la sesión ya está
   escalada a un humano, el bot no responde (flujo distinto, no cubierto
   aquí).
2. **Recuperación** (`retrieve_context` → `app/rag/retriever.py::retrieve`):
   la pregunta se convierte en un embedding (`embed_query`) y se busca
   contra el índice FAISS los fragmentos más similares, más una búsqueda
   léxica en paralelo (BM25, ver
   [busqueda-lexica-bm25.md](busqueda-lexica-bm25.md)) -- sin ninguna
   llamada a Groq. El costo real cambió respecto a una medición anterior
   de este documento (~20ms): ese número era de antes de que existiera el
   re-ranking con el pool de candidatos actual. Medido en producción hoy
   (VPS de 2 núcleos): `embed_query` ~400ms, la búsqueda por FAISS y la
   léxica (BM25) unos pocos ms cada una, y el **re-ranking es ahora el
   costo dominante** -- entre ~500ms y varios segundos, según cuántos
   candidatos haya que comparar y qué tan cargada esté la CPU del
   servidor en ese momento (es una operación de CPU, no de red).
2.b **Reformulación/condensación** (`_try_multi_query_rewrite`, en
   `chat_service.py`) -- si la recuperación anterior no encontró nada
   relevante, o la pregunta es un seguimiento corto (5 palabras o menos,
   ej. "precio") con historial de conversación previo (así haya
   encontrado *algo*, puede ser ruido sin el contexto de qué se venía
   hablando), el sistema reintenta antes de darse por vencido:
   - **Con historial de conversación:** le pide a Groq
     (`llm.rewrite_query_variations`) 2-3 formas alternativas de plantear
     la pregunta combinando el historial reciente (ej. "precio" después
     de hablar de "Ingeniería en TIC" -> "precio de Ingeniería en TIC"),
     y repite la búsqueda con cada variación.
   - **Sin historial, pregunta larga y elaborada** (6 palabras o más,
     `_worth_condensing`): en vez de reformular con contexto (no hay
     ninguno), le pide a Groq (`llm.condense_query_for_search`) que
     quite el relleno conversacional ("buenas, disculpe la molestia,
     no estoy seguro pero...") antes de vectorizarla -- ese tipo de
     frase mide una similitud de embeddings mucho más baja que la misma
     pregunta dicha directo, aunque el significado sea el mismo.
   - En ambos casos, el resultado final se re-rankea contra la variante
     que sí encontró resultados (no contra la pregunta original) y se
     usa esa variante -- no la original -- para el resto del pipeline
     (`retrieval_question`).
   - **Costo:** esta reformulación agrega una llamada extra a Groq
     (contada aparte en `retrieval_ms`) solo en los casos descritos
     arriba -- una pregunta que ya encuentra buen contexto en el primer
     intento no paga este costo.
3. Se arma el `CONTEXTO` concatenando esos fragmentos (`build_context`) y
   se trae el historial reciente de la conversación (`get_history`).
4. Se emite el primer evento SSE: `{"type": "meta", "sources": [...]}`,
   con los documentos recuperados (deduplicados por documento+página,
   ver `_dedup_sources`). Esto es una lista **preliminar**: son los
   fragmentos que pasaron el re-ranking y se le pasaron al LLM como
   contexto, no una confirmación de que el LLM usó cada uno en la
   respuesta final -- el paso 6 la reemplaza por la lista definitiva.
5. **Caché de respuesta** (`answer_cache_service.try_get_cached_answer`)
   -- antes de llamar a Groq, se calcula una huella (`context_hash`) de
   los fragmentos recuperados (no de la pregunta) y se busca una
   respuesta ya generada para ese mismo contexto exacto. Si hay
   coincidencia y la pregunta tiene 3 palabras o más, se reutiliza esa
   respuesta sin llamar a Groq -- ver la sección "Caché de respuestas"
   más abajo.

## 4. Llamada a Groq -- `app/rag/llm.py::stream_answer` y `_create_completion`

Solo ocurre si el paso 5 anterior **no** encontró una respuesta cacheada
para reutilizar -- en un acierto de caché, el resto de esta sección se
salta por completo y `full_answer` se llena directo con el texto
cacheado (sigue emitiéndose como un único `delta`, así que el navegador
no distingue una respuesta cacheada de una generada en el momento).

- Se arma el arreglo de mensajes: prompt de sistema (reglas estrictas de
  "solo responder con el CONTEXTO", más la fecha actual de la
  institución -- `INSTITUTION_TIMEZONE`, vía `tzdata` -- para que el
  LLM pueda resolver preguntas relativas como "¿hoy hay clase de
  álgebra?" comparando contra el día de la semana que trae el CONTEXTO)
  + historial + la pregunta con el CONTEXTO adjunto (`build_messages`).
- Todo pasa por `_create_completion(purpose, ...)`, el único punto de
  salida hacia la API de Groq en todo el proyecto:
  - `_rate_limiter.acquire(estimated_tokens)` -- si el cupo por minuto de
    la cuenta está agotado, **aquí es donde el request se queda esperando**
    antes de llamar a Groq. Es la causa real detrás de picos de varios
    segundos (o hasta ~55s en pruebas intensivas), no un problema de Groq
    en sí ni de este código de streaming.
  - Se llama a `client.chat.completions.create(..., stream=True)`.
  - Se registra la llamada en la tabla `groq_calls` (`purpose="stream_answer"`,
    éxito o fallo), para poder auditar después cuántas llamadas reales se
    hicieron y de qué tipo.
- Groq empieza a devolver la respuesta en fragmentos ("deltas").

## 5. Streaming de vuelta al navegador

- Por cada delta que llega, `stream_answer` emite
  `{"type": "delta", "text": "..."}`.
- En `script.js`, cada delta se acumula y **se vuelve a renderizar todo el
  texto acumulado como markdown** (`bubble.innerHTML =
  renderMarkdownHtml(answerText)`, usando `marked` + `DOMPurify` --
  ver `frontend/markdown-render.js`). Así es como la respuesta va
  apareciendo con negritas/listas ya formateadas, no como texto plano.

## 6. Cierre del turno

- Antes que nada, se separa la línea `FUENTES_USADAS: doc1.txt, doc2.pdf`
  que el LLM agrega al final de su respuesta (`llm.extract_used_sources`,
  regla 8 del prompt de sistema) -- nunca se le muestra al estudiante
  (se recorta tanto en el backend como, por si acaso, en el frontend
  mientras llega por streaming). Con esa lista, `_filter_chunks_by_used_sources`
  descarta de las fuentes finales cualquier fragmento que haya pasado el
  umbral de re-ranking pero que el LLM reporte no haber usado de verdad
  para responder -- evita citar "ruido" que técnicamente pasó el filtro
  pero no aportó nada a la respuesta. Si el LLM no reportó ninguna fuente
  reconocible (o la regla falla por cualquier motivo), se muestran todas
  las recuperadas -- nunca queda peor que antes de este mecanismo.
- Se calcula `generation_ms` (tiempo desde justo antes de la llamada
  hasta el último delta, o ~0 en un acierto de caché) y se guarda en
  `chat_metrics` junto con `retrieval_ms`, `chunks_retrieved` y
  `cache_hit` (`record_chat_metrics`).
- Se guarda el turno completo (pregunta + respuesta, y las fuentes ya
  filtradas) en la tabla `turns` (`_save_and_broadcast_turn` →
  `append_turn`).
- Se emite el evento final `{"type": "done", "sources": [...],
  "suggestions": [...], "metrics": {...}}`.
- El navegador cierra el ciclo de lectura del stream, muestra el bloque
  "Archivos consultados" con las fuentes de **este** evento `done` --
  **reemplazan**, no complementan, a las preliminares del evento `meta`
  del paso 3 -- y reactiva el botón de enviar.

## Caché de respuestas por contexto (`app/services/answer_cache_service.py`)

El prompt de sistema obliga al LLM a responder únicamente con el
`CONTEXTO` recuperado, así que lo que determina la respuesta es **qué
fragmentos se recuperaron**, no la redacción exacta de la pregunta. Dos
preguntas distintas ("¿cuánto cuesta el semestre?" / "precio del
semestre") que terminan recuperando los mismos fragmentos comparten
`context_hash` (hash de `chunk_id:texto` de cada fragmento, sin importar
el orden) y reutilizan la misma respuesta ya generada -- sin gastar una
llamada a Groq.

- **No elegible para caché:** contexto vacío (sin información
  suficiente, o un saludo) o pregunta de menos de 3 palabras (`sí`,
  `gracias`, `¿y el costo?` suelen depender de lo que se dijo antes en
  la conversación -- no es seguro reutilizar una respuesta cacheada ahí).
- **No se cachea** la respuesta fija de "no encontré información
  suficiente" -- no aporta nada reutilizarla.
- **Invalidación automática:** si el texto de origen cambia (se edita un
  documento y se reingesta), el conjunto/contenido de fragmentos
  recuperados cambia, el `context_hash` ya no coincide, y la entrada
  vieja simplemente deja de usarse -- sin tener que clasificar a mano
  qué información es "cambiante" y cuál no.
- Se cachea el texto **crudo** de la respuesta (con la línea
  `FUENTES_USADAS` todavía incluida) para que una respuesta servida
  desde caché también se pueda filtrar por fuentes usadas la próxima
  vez.

## Medición real (dos preguntas idénticas, mismo estudiante)

> Ejemplo puntual capturado el 2026-09-05 durante una sesión de pruebas
> manuales, para ilustrar el flujo -- no es un benchmark permanente del
> sistema. Los tiempos varían según carga, tamaño de la respuesta y el
> cupo disponible del limitador de tasa de Groq en ese momento. **Nota:**
> esta medición es anterior a la caché de respuestas descrita arriba --
> en ese momento el proyecto todavía no la tenía, así que las dos
> llamadas a Groq fueron independientes. Con la caché ya en producción,
> repetir la misma pregunta (si el contexto recuperado es idéntico)
> mostraría un `generation_ms` cercano a cero en la segunda vez, en vez
> de un tiempo similar al de la primera.

| | Pregunta 1 (07:45:07 UTC) | Pregunta 2 (07:52:50 UTC) |
|---|---|---|
| `retrieval_ms` | 19.78 | 19.44 |
| `generation_ms` | 704.66 | 514.73 |
| Longitud de la respuesta | 314 caracteres | 290 caracteres |

En su momento, esto confirmó que **no había caché ni reutilización de
respuestas**: cada pregunta repetía las 6 etapas desde cero. Las dos
respuestas fueron similares en tiempo y tamaño porque Groq generó dos
respuestas independientes para la misma pregunta, con contexto
recuperado casi idéntico -- no porque una se haya reutilizado.
