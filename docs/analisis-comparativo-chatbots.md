# Chatbot RAG vs. chatbot tradicional: ventajas, desventajas y cuándo usar cada uno

Este documento resume el análisis comparativo entre el enfoque de este
proyecto (RAG: recuperación de documentos + generación con LLM) y un
"chatbot tradicional", entendiendo por esto dos variantes comunes:

- **Basado en reglas / árbol de decisión**: menús, botones, "si el usuario
  escribe X, responde Y" -- sin modelo de lenguaje de por medio.
- **LLM genérico sin conexión a documentos**: un asistente conversacional
  que responde de memoria, sin anclarse a una base documental propia.

Sirve como referencia para justificar la elección de arquitectura (por
ejemplo, en una sustentación) y como guía práctica para decidir, a
futuro, si un caso de uso nuevo encaja mejor con este enfoque o con uno
más simple.

## 1. Ventajas de este chatbot

1. **Respuestas ancladas a documentos reales, no a memoria del modelo** --
   el LLM solo puede responder con lo que está literalmente en el
   CONTEXTO recuperado (ver el prompt de sistema en `app/rag/llm.py`,
   reglas 2 y 4). Un bot de reglas tampoco "inventa", pero solo cubre lo
   que alguien programó explícitamente; un LLM genérico sin RAG sí puede
   alucinar datos institucionales.
2. **Se actualiza subiendo un archivo, no reprogramando** -- agregar o
   cambiar una política es subir un documento desde `/root` o `/panel`,
   no editar un árbol de decisión ni reentrenar un modelo. La vigencia
   por documento (`app/rag/retriever.py::drop_superseded_by_vigencia`)
   incluso resuelve sola cuál versión citar cuando hay varias. Incluso se
   puede alimentar de golpe con el contenido público de un sitio web
   completo (rastreo automático), sin subir archivo por archivo.
3. **Sabe decir "no sé"** -- reconoce explícitamente cuando no tiene
   información suficiente (`settings.NO_INFO_MESSAGE` +
   `has_sufficient_info`), en vez de forzar una respuesta genérica o
   inventar. Los bots de reglas tienden a un "no entendí" ciego cuando la
   pregunta no calza con ningún patrón previsto.
4. **Entiende variaciones de lenguaje natural** -- "¿cuánto dura la
   carrera?" y "¿cuántos semestres tiene?" llegan al mismo contenido
   gracias a embeddings + reformulación de preguntas de seguimiento
   (multi-query retrieval, `app/rag/llm.py::rewrite_query_variations`).
   Un bot de reglas necesita anticipar cada forma de preguntar.
5. **Mejora medible con uso real** -- feedback 👍/👎, el dashboard de
   "preguntas sin respuesta suficiente", y la evaluación automatizada
   (`evaluation/evaluate.py`) dan señales concretas de dónde falta
   contenido o dónde bajó la calidad -- así se detectó y corrigió, por
   ejemplo, una mala calibración del re-ranking que causaba respuestas
   erróneas por confusión de años.
6. **Escalamiento a humano integrado**, no un callejón sin salida --
   cuando no hay información, ofrece conectar con un asesor real (con
   panel en vivo por dependencia/general), algo que muchos bots de reglas
   no resuelven con la misma fluidez.
7. **Control de costo ya construido** -- caché de respuestas por huella de
   contexto (evita repetir llamadas al LLM para preguntas equivalentes),
   límite de tasa por IP, y re-ranking local con cross-encoder (sin costo
   de API) en vez de un LLM adicional para juzgar relevancia.

## 2. Desventajas / trade-offs reales

1. **Más piezas móviles que uno de reglas** -- embeddings, FAISS,
   cross-encoder, LLM externo (Groq), caché, vigencia: cada una puede
   fallar o descalibrarse (ya ocurrió con `RERANK_MIN_SCORE`). Un árbol
   de decisión es mucho más fácil de auditar por completo de un vistazo.
2. **Depende de un proveedor externo (Groq)** -- una caída, un límite de
   tasa, o un cambio de política/modelo del proveedor afecta al chatbot.
   Un bot de reglas no depende de ningún servicio de terceros para
   funcionar.
3. **La calidad depende de la calidad y mantenimiento de los documentos**
   -- un documento mal escrito, desactualizado o ambiguo se hereda
   directamente en las respuestas. Exige disciplina administrativa
   continua (curar contenido, asignar vigencia, revisar el dashboard) que
   un bot de reglas simple no exige de la misma forma.
4. **Latencia variable, no instantánea** -- recuperación + re-ranking +
   generación toma de cientos de milisegundos a varios segundos (más si
   hay que reformular la pregunta con una llamada extra al LLM), contra
   la respuesta prácticamente instantánea de un árbol de decisión o un
   menú de botones.
5. **Menos control exacto sobre la redacción** -- un bot de reglas
   garantiza exactamente el texto que un humano escribió. Aquí el LLM
   redacta la respuesta a partir del contexto, así que la redacción varía
   entre preguntas equivalentes aunque el contenido factual sea el mismo.
6. **No es determinista al 100%** -- la misma pregunta formulada de dos
   formas distintas puede recuperar conjuntos de fragmentos ligeramente
   distintos (mitigado con caché y umbrales, pero no eliminado), algo que
   no ocurre en un flujo de reglas fijo.
7. **Requiere más conocimiento técnico para mantenerlo** -- ajustar
   umbrales de similitud, recalibrar el re-ranking, o diagnosticar por
   qué una pregunta no encontró información exige entender el pipeline
   completo, no solo editar un guion de conversación.

**En una frase:** se gana precisión, naturalidad y escalabilidad de
contenido a cambio de más complejidad operativa y una dependencia
externa -- trade-off razonable para un volumen de preguntas real y
variado como el de una institución educativa, pero no gratis.

## 3. Cuándo conviene este chatbot en vez de uno tradicional

1. **Volumen alto de preguntas variadas sobre contenido que cambia** --
   reglamentos, calendarios, precios, requisitos de programas: hay
   demasiadas formas de preguntar lo mismo para programarlas a mano, y el
   contenido se actualiza con frecuencia (el problema que resuelve la
   vigencia por documento). Un bot de reglas necesitaría reescribirse
   cada semestre.
2. **Multi-dependencia con contenido que crece de forma descentralizada**
   -- cada facultad/oficina sube y mantiene sus propios documentos sin
   tocar código ni pedir que un desarrollador agregue una rama nueva al
   árbol de decisión.
3. **Cuando "no sé, pero te conecto con alguien" es aceptable y valioso**
   -- el flujo de escalamiento convierte cada pregunta sin respuesta en
   una oportunidad de mejora (feedback + dashboard), en vez de un
   callejón sin salida. Requiere que la institución sí tenga personal
   disponible para atender esos casos.
4. **El usuario no sabe cómo se llama lo que busca** -- un estudiante no
   sabe si su pregunta es "trámite de grado", "requisitos de grado" o
   "proceso de titulación". Un menú de botones lo obliga a adivinar la
   categoría correcta; la búsqueda semántica no.
5. **Se necesita trazabilidad de qué se citó y de dónde** -- cada
   respuesta muestra "Archivos consultados" con opción de descarga del
   original. Para una institución donde la exactitud legal/administrativa
   importa, poder señalar la fuente exacta es más defendible que una
   respuesta de guion sin referencia.
6. **Se quiere medir y mejorar con datos reales** -- si hay intención de
   iterar (ver qué preguntas fallan, qué respuestas no gustan, y corregir
   documentación en consecuencia), el dashboard + feedback + evaluación
   automatizada dan señal accionable. Un bot de reglas no genera esa
   retroalimentación por sí solo.

## 4. Cuándo NO conviene (mejor un chatbot tradicional)

1. **Universo de preguntas pequeño y fijo** -- ej. un bot de 5-10
   preguntas frecuentes que casi nunca cambian ("horario de atención",
   "dirección de la sede"). Ahí un árbol de decisión es más barato de
   construir, más rápido de responder, y 100% predecible -- el RAG es
   sobre-ingeniería.
2. **Se necesita control legal exacto de la redacción** -- si cada
   palabra de la respuesta debe ser aprobada literalmente por
   legal/compliance (ej. términos de un contrato, una alerta de
   seguridad), un guion fijo es más seguro que dejar que un LLM redacte,
   aunque esté anclado a contexto.
3. **No hay quien mantenga documentos ni revise el dashboard** -- si
   nadie va a subir/actualizar archivos, asignar vigencia, ni mirar qué
   preguntas fallan, el chatbot degrada con el tiempo (contenido
   desactualizado) mientras que un flujo de reglas simple, una vez hecho,
   no se "pudre" solo.
4. **Presupuesto o tolerancia cero a dependencias externas** -- si no se
   puede depender de un proveedor de LLM (por política, presupuesto, o
   requisito de que todo corra 100% on-premise sin ningún servicio
   externo), un bot de reglas evita ese riesgo por completo.
5. **La interacción es realmente transaccional, no conversacional** --
   "agendar una cita", "pagar una factura": ahí un flujo guiado paso a
   paso (botones, formularios) es más rápido y menos propenso a fallos
   que dejar que el usuario escriba libremente.

**Regla práctica:** si el contenido cambia con el tiempo, es voluminoso,
y las preguntas se formulan de muchas maneras distintas → RAG. Si el
contenido es fijo, pequeño, y la redacción exacta importa más que la
flexibilidad → reglas.
