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
   contra el índice FAISS los fragmentos más similares. Es la parte
   barata: en la medición real tomó **~20ms**, sin ninguna llamada a Groq.
3. Se arma el `CONTEXTO` concatenando esos fragmentos (`build_context`) y
   se trae el historial reciente de la conversación (`get_history`).
4. Se emite el primer evento SSE: `{"type": "meta", "sources": [...]}`,
   con los documentos recuperados (deduplicados por documento+página,
   ver `_dedup_sources`). Esto es lo que el frontend guarda para mostrar
   luego como "Archivos consultados" -- son los fragmentos que se le
   pasaron al LLM como contexto, no una confirmación de que el LLM usó
   cada uno en la respuesta final.

## 4. Llamada a Groq -- `app/rag/llm.py::stream_answer` y `_create_completion`

- Se arma el arreglo de mensajes: prompt de sistema (reglas estrictas de
  "solo responder con el CONTEXTO") + historial + la pregunta con el
  CONTEXTO adjunto (`build_messages`).
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

- Al terminar el stream de Groq, se calcula `generation_ms` (tiempo desde
  justo antes de la llamada hasta el último delta) y se guarda en
  `chat_metrics` junto con `retrieval_ms` y `chunks_retrieved`
  (`record_chat_metrics`).
- Se guarda el turno completo (pregunta + respuesta) en la tabla `turns`
  (`_save_and_broadcast_turn` → `append_turn`).
- Se emite el evento final `{"type": "done", "suggestions": [...], "metrics": {...}}`.
- El navegador cierra el ciclo de lectura del stream, muestra el bloque
  "Archivos consultados" con las fuentes que ya tenía del evento `meta`, y
  reactiva el botón de enviar.

## Medición real (dos preguntas idénticas, mismo estudiante)

> Ejemplo puntual capturado el 2026-09-05 durante una sesión de pruebas
> manuales, para ilustrar el flujo -- no es un benchmark permanente del
> sistema. Los tiempos varían según carga, tamaño de la respuesta y el
> cupo disponible del limitador de tasa de Groq en ese momento.

| | Pregunta 1 (07:45:07 UTC) | Pregunta 2 (07:52:50 UTC) |
|---|---|---|
| `retrieval_ms` | 19.78 | 19.44 |
| `generation_ms` | 704.66 | 514.73 |
| Longitud de la respuesta | 314 caracteres | 290 caracteres |

Confirma que **no hay caché ni reutilización de respuestas**: cada
pregunta repite las 6 etapas desde cero. Las dos respuestas son similares
en tiempo y tamaño porque Groq generó dos respuestas independientes para
la misma pregunta, con contexto recuperado casi idéntico -- no porque una
se haya reutilizado.
