# Stack tecnológico del proyecto

Resumen del stack completo del chatbot, con descripciones cortas pensadas
para exponer (una o dos frases por tecnología, listas para decir en voz
alta). Para el razonamiento completo de "por qué esto y no otra opción",
ver el [README.md](../README.md) (sección 5) y
[decision-uso-de-groq.md](decision-uso-de-groq.md).

## 1. Arquitectura en una frase

Un chatbot RAG (Retrieval-Augmented Generation) multi-dependencia: antes
de responder, busca los fragmentos más relevantes en los documentos
oficiales de la dependencia correspondiente mediante búsqueda semántica
local, y solo entonces le pide al modelo de lenguaje que responda basado
exclusivamente en ese contexto — así evita inventar información.

## 2. Backend

| Tecnología | Descripción corta para exponer |
|---|---|
| **Python 3.12** | Lenguaje del backend completo: API, pipeline de IA, scripts de administración. |
| **FastAPI** | Framework web para la API REST y los WebSockets; genera automáticamente documentación interactiva (Swagger) en `/docs`. |
| **Uvicorn** | Servidor ASGI que ejecuta la aplicación FastAPI en producción. |
| **Pydantic** | Valida y tipa cada petición/respuesta de la API (contratos de datos), evitando errores de formato antes de que lleguen a la lógica de negocio. |
| **SQLite** | Base de datos del historial de conversaciones, sesiones, administradores, dependencias y FAQ — un solo archivo, sin necesidad de un servidor de base de datos aparte. |
| **bcrypt** | Hashea las contraseñas de los administradores; nunca se guarda ni se transmite una contraseña en texto plano. |
| **WebSockets** (nativo de FastAPI/Starlette) | Comunicación en tiempo real: el estudiante ve la respuesta del asesor al instante, y el panel de administración recibe nuevas conversaciones sin recargar la página. |

## 3. Inteligencia artificial / pipeline RAG

| Tecnología | Descripción corta para exponer |
|---|---|
| **Groq (GroqCloud)** | Proveedor del modelo de lenguaje (LLM) en la nube; se eligió por su velocidad (~1000 tokens/segundo, gracias a su chip propio LPU) y por tener un nivel gratuito funcional para un proyecto académico. |
| **openai/gpt-oss-20b** | El modelo de lenguaje específico que usa el chatbot para generar respuestas, corriendo sobre la infraestructura de Groq. |
| **Sentence Transformers** (`paraphrase-multilingual-MiniLM-L12-v2`) | Genera los *embeddings* (representación numérica del significado de un texto) de forma local y gratuita — no depende de una API externa ni de Groq. |
| **FAISS** (Facebook AI Similarity Search) | Base de datos vectorial: almacena los embeddings de todos los documentos e indexa la búsqueda semántica por similitud de significado, no por coincidencia exacta de palabras. |
| **Limitador de tasa propio** | Controla cuántas peticiones por minuto se le envían a Groq, para no exceder el límite del plan gratuito (30 peticiones/min) — las peticiones esperan su turno en vez de fallar. |

## 4. Frontend

| Tecnología | Descripción corta para exponer |
|---|---|
| **HTML + CSS + JavaScript puro** | Sin frameworks (React, Vue, etc.): tres interfaces livianas — el chat del estudiante, el panel de atención para asesores, y el panel de administración para el root. |
| **Server-Sent Events (SSE)** | El chat del estudiante recibe la respuesta del bot palabra por palabra, en streaming, en vez de esperar a que se genere completa. |

## 5. Procesamiento de documentos

| Tecnología | Descripción corta para exponer |
|---|---|
| **pypdf** | Extrae el texto de documentos PDF. |
| **python-docx** | Extrae el texto de documentos Word (.docx). |
| **openpyxl** | Extrae los datos de hojas de cálculo Excel (.xlsx) — cada fila se indexa como un registro independiente, para poder consultar un dato puntual (un horario, un salón). |

## 6. Testing

| Tecnología | Descripción corta para exponer |
|---|---|
| **pytest** | Framework de pruebas automatizadas; el proyecto tiene más de 115 pruebas que corren sin necesidad de una clave real de Groq (todo lo que llama al LLM se simula). |
| **httpx / TestClient** (FastAPI) | Permite probar los endpoints de la API completos (peticiones HTTP reales contra la app) dentro de las pruebas automatizadas. |

## 7. Infraestructura y despliegue

| Tecnología | Descripción corta para exponer |
|---|---|
| **VPS Linux (Ubuntu Server)** | Servidor propio donde corre el chatbot en producción — necesario porque el proyecto requiere un proceso siempre encendido (WebSockets, tareas en segundo plano), algo que un hosting compartido normalmente no permite. |
| **systemd** | Mantiene el proceso del chatbot corriendo permanentemente en el servidor, reiniciándolo automáticamente si llega a fallar. |
| **nginx** | Actúa como proxy inverso: recibe las peticiones públicas y las reenvía al proceso interno del chatbot, incluyendo el manejo especial que necesitan los WebSockets. |
| **Let's Encrypt** (HTTPS) | Certificado SSL/TLS gratuito para que el sitio funcione bajo `https://` en vez de `http://`. |
| **Git + GitHub** | Control de versiones del código; el servidor de producción se actualiza con `git pull` cada vez que hay un cambio nuevo. |

## 8. Seguridad implementada

- Autenticación real por cuenta (usuario + contraseña con bcrypt) para cada administrador, con sesiones propias — nada de una clave compartida.
- Control de acceso por rol (root / general / dependencia): cada administrador solo ve y actúa sobre lo que le corresponde.
- Límite de peticiones (rate limiting) tanto en el chat público como en el login, para frenar abuso y fuerza bruta.
- Validación de extensión y tamaño máximo antes de procesar cualquier documento subido.
- El modelo de lenguaje solo responde con información de los documentos oficiales — nunca inventa datos, y lo dice explícitamente cuando no tiene información suficiente.
