# Guía para exponer/sustentar el proyecto

Material de apoyo para presentar este proyecto (asignatura de Inteligencia
Artificial): qué decir, en qué orden, qué demostrar en vivo, y cómo
responder las preguntas más probables. No reemplaza los documentos
técnicos -- los referencia para que puedas profundizar si te preguntan
algo puntual.

## 1. El proyecto en una frase

> Una plataforma de chatbot institucional multi-dependencia: cualquier
> organización registra sus áreas (facultades, oficinas, departamentos) y
> las alimenta con su propia documentación; el chatbot responde
> **únicamente** con esa documentación oficial y redirige a un asesor
> humano de la dependencia correspondiente cuando no tiene suficiente
> información -- con un panel de administración completo por roles para
> gestionar documentos, conversaciones y equipo.
>
> Este repositorio incluye como ejemplo real la instalación de la
> Universidad Libre - Seccional Cúcuta (Facultad de Ingeniería) -- úsala
> como caso concreto en la demo, pero aclara que el sistema no está
> limitado a una sola facultad.

## 2. Estructura sugerida (12-15 minutos)

1. **Problema y solución** (2 min) -- sección 3.
2. **Qué es RAG y por qué se usó** (2-3 min) -- sección 3.
3. **Demo en vivo** (5-6 min) -- sección 4, es la parte más importante.
4. **Decisiones técnicas clave** (2 min) -- sección 5, solo menciona 2-3,
   no las 6.
5. **Evidencia de que funciona** (1-2 min) -- sección 6, el reporte de
   evaluación.
6. **Cierre + preguntas** -- sección 7 tiene las respuestas preparadas.

## 3. Cómo explicar RAG sin asumir que la audiencia lo conoce

Analogía útil: **es la diferencia entre un examen a libro cerrado y uno a
libro abierto.** Un LLM "normal" responde solo con lo que aprendió durante
su entrenamiento (libro cerrado) -- no sabe nada específico de tu
institución, y si le preguntas igual puede inventar una respuesta con
seguridad (alucinación). RAG (Retrieval-Augmented Generation) le da al
modelo el material correcto justo antes de responder (libro abierto): en
vez de confiar en lo que "recuerda", el sistema busca los fragmentos más
relevantes de los documentos reales y se los entrega en el mismo mensaje.

Tres pasos, en una oración cada uno:

1. **Retrieval (recuperar)**: la pregunta se compara contra los
   documentos ya indexados y se traen los fragmentos más parecidos.
2. **Augmented (aumentar)**: esos fragmentos se agregan al mensaje que se
   le envía al modelo, como "contexto".
3. **Generation (generar)**: el modelo redacta la respuesta, con la regla
   explícita de usar *solo* ese contexto -- si no hay información
   suficiente, debe decirlo en vez de inventar.

Para el detalle técnico completo de estos tres pasos, ver
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md) y
[conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md).

## 4. Demo en vivo -- guion sugerido

Practica esta secuencia antes de exponer; es la parte que más impresiona
porque se ve el sistema completo funcionando de punta a punta.

1. **Pregunta con buena respuesta**: en el chat de estudiante, pregunta
   algo que sí está en los documentos (ej. "¿Qué programas ofrece la
   facultad?"). Señala: la respuesta aparece progresivamente (streaming),
   con formato (listas/negritas), y al final el bloque "Archivos
   consultados" -- prueba visual de que no inventó nada.
2. **Pregunta sin información suficiente**: pregunta algo que no está en
   los documentos. El bot debe decir explícitamente que no tiene
   información suficiente (no inventar) y ofrecer **"Solicitar atención
   humana"**. Este es el momento para explicar la regla anti-alucinación
   del prompt.
3. **Escalación en tiempo real**: completa el formulario de escalación.
   Cambia a la pestaña del panel (`/panel`, ya con sesión abierta de
   antemano) y muestra que la conversación **aparece sola**, sin recargar
   -- es WebSocket, no polling.
4. **Responder como asesor**: usa "Preguntar al asistente" para pedirle
   una sugerencia al bot, o responde manualmente. Marca como resuelto.
5. **FAQ automática**: cambia a `/root` → pestaña "Preguntas frecuentes"
   y muestra la propuesta que el sistema generó solo, a partir de esa
   conversación resuelta.
6. **Subir un documento nuevo**: sube un archivo corto de prueba (TXT es
   el más rápido de mostrar) en la pestaña "Documentos", y de inmediato
   pregúntale al chat algo que solo esté en ese archivo -- demuestra que
   no hace falta reiniciar nada ni "reconstruir" manualmente.
7. **Dashboard**: cierra con la pestaña "Dashboard" de `/root` -- un
   vistazo rápido a los números agregados de todo el sistema.

## 5. Decisiones técnicas clave (menciona 2-3, no todas)

| Decisión | Por qué (una línea) | Detalle completo |
|---|---|---|
| Groq como proveedor del LLM | Nivel gratuito real (no trial), y muy rápido gracias a su hardware propio (LPU) | [decision-uso-de-groq.md](decision-uso-de-groq.md) |
| FAISS en vez de ChromaDB | ChromaDB no instala fácil en Windows sin compilador; FAISS sí | [conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md) |
| PDF/DOCX se convierten a `.txt` al subir | Hasta 44x más lento reprocesar un DOCX que un TXT en cada reconstrucción del índice (medido) | [notas-mejora-documentos.md](notas-mejora-documentos.md) |
| Ingesta incremental (no reconstruir todo el índice) | Subir un documento nuevo no debe recalcular los embeddings de los demás | [flujo-subida-documentos.md](flujo-subida-documentos.md) |
| Regla estricta "solo responde con el CONTEXTO" en el prompt | Es la defensa principal contra alucinaciones -- si no está en los documentos, debe decir que no sabe | `app/rag/llm.py::_build_system_prompt` |

## 6. Evidencia cuantitativa de que funciona

El proyecto incluye un script de evaluación académica
(`evaluation/evaluate.py`) que corre un set de preguntas de prueba y
verifica automáticamente:

- Si el sistema recupera el documento/fuente correcta para cada pregunta.
- Si la respuesta contiene las palabras clave esperadas.
- Si reconoce correctamente cuándo NO tiene información suficiente (para
  no inventar).

```powershell
venv\Scripts\python.exe evaluation\evaluate.py
```

El resultado queda en `evaluation/last_report.json`. Correrlo (o mostrar
un reporte ya generado) antes de la exposición te da un número concreto
que respaldar en vez de solo afirmaciones -- por ejemplo "el sistema
acertó la fuente correcta en X de Y preguntas de prueba".

## 7. Preguntas probables y respuestas preparadas

**¿Por qué RAG y no simplemente afinar (fine-tuning) el modelo con los
documentos de la institución?**
Fine-tuning es costoso, hay que rehacerlo cada vez que un documento
cambia, y no elimina las alucinaciones (el modelo sigue "recordando" en
vez de consultar). RAG permite actualizar el conocimiento con solo subir
un documento nuevo, sin reentrenar nada, y cita la fuente exacta de cada
respuesta.

**¿Por qué Groq y no OpenAI u otro proveedor?**
Nivel gratuito genuino (no un trial con caducidad) suficiente para tráfico
académico, y latencia muy baja gracias a su hardware propio (LPU). Ver
[decision-uso-de-groq.md](decision-uso-de-groq.md) para el análisis
completo, incluyendo los riesgos (límites de tasa, dependencia de un
proveedor externo).

**¿Cómo evitan que el bot invente información?**
Dos capas: (1) el prompt de sistema le prohíbe explícitamente usar
conocimiento propio, solo el CONTEXTO recuperado, y (2) si no se
encuentran fragmentos relevantes, el flujo ni siquiera intenta generar una
respuesta de contenido -- responde con el mensaje fijo de "no encontré
información" y ofrece escalar a un humano.

**¿Qué pasa si Groq falla o se agota el cupo gratuito?**
Hay un limitador de tasa propio (`app/rag/rate_limiter.py`) que espera su
turno en vez de fallar cuando se acerca al límite. Si Groq responde con
error, el usuario ve un mensaje de error controlado, no una pantalla
rota -- ver `app/api/routes.py::chat_stream`.

**¿Cómo escala esto a muchos documentos o muchos usuarios?**
La búsqueda semántica (FAISS) es del orden de milisegundos incluso con
miles de fragmentos. El cuello de botella real sería el límite de tasa de
la cuenta gratuita de Groq con muchos usuarios simultáneos -- pasar a un
plan pago de Groq resolvería eso sin cambiar arquitectura.

**¿Es seguro el sistema de administración?**
Contraseñas con `bcrypt` (nunca en texto plano), sesiones con token
propio y expiración, control de acceso por rol (root/general/dependencia)
verificado en cada endpoint, y límite de intentos de login. Ver la sección
de seguridad en el [README.md](../README.md).

**¿Cómo saben que el sistema realmente responde bien y no solo "parece"
funcionar?**
El script de evaluación (sección 6) mide esto de forma objetiva y
repetible, no por impresión subjetiva.
