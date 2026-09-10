# Estructura del proyecto (directorios y archivos)

Este documento explica para qué sirve cada carpeta y archivo del
repositorio. Para el "por qué" de las decisiones técnicas ver el
[README.md](../README.md) y [stack-tecnologico.md](stack-tecnologico.md);
para cómo *usar* el sistema ver [manual-usuario.md](manual-usuario.md).

## Árbol completo

```
chatbot-master/
├── app/                          # Todo el backend (Python/FastAPI)
│   ├── main.py                   # Punto de entrada: arma la app, sirve el frontend, tareas de fondo
│   ├── config.py                 # Configuración centralizada, lee .env
│   ├── api/
│   │   ├── routes.py             # TODOS los endpoints de la API
│   │   └── security.py           # Autenticación de administradores, rate limiting
│   ├── rag/                      # Núcleo del pipeline RAG (búsqueda + IA)
│   │   ├── document_loader.py    # Extrae texto de PDF/DOCX/TXT/XLSX
│   │   ├── chunker.py            # Divide el texto en fragmentos indexables
│   │   ├── embeddings.py         # Genera los vectores semánticos (local)
│   │   ├── vector_store.py       # Base vectorial FAISS + índice léxico BM25 (guardar/buscar/borrar)
│   │   ├── retriever.py          # Combina búsqueda semántica + léxica, re-rankea
│   │   ├── reranker.py           # Re-ranking local (cross-encoder) de los candidatos recuperados
│   │   ├── llm.py                # Cliente Groq: prompts, reformulación/condensación de preguntas y llamadas al modelo
│   │   ├── rate_limiter.py       # Autolímite de peticiones/tokens hacia Groq
│   │   └── web_crawler.py        # Rastreo BFS de un sitio web (normaliza URLs, respeta robots.txt, sigue enlaces internos)
│   ├── services/                 # Lógica de negocio (usada por las rutas)
│   │   ├── chat_service.py       # Orquesta el pipeline completo de una pregunta
│   │   ├── ingest_service.py     # Ingestión de documentos (completa e incremental)
│   │   ├── crawl_job_service.py  # Job de rastreo web en hilo de fondo (progreso, cancelación, archivos pendientes)
│   │   ├── history.py            # Base de datos SQLite: sesiones, mensajes, admins, dependencias
│   │   ├── admin_service.py      # Autenticación y CRUD de administradores/dependencias
│   │   ├── dashboard_service.py  # Agregación de datos para el dashboard de actividad (root/general/dependencia)
│   │   ├── faq_service.py        # Propuestas de FAQ auto-generadas
│   │   ├── answer_cache_service.py  # Caché de respuestas por huella del contexto recuperado
│   │   ├── hostility_service.py  # Detección de hostilidad hacia el chatbot y bloqueo temporal
│   │   ├── widget_service.py     # Orígenes autorizados a embeber el chat (/widget)
│   │   └── ws_manager.py         # Conexiones WebSocket (chat en vivo, panel)
│   └── models/
│       └── schemas.py            # Contratos Pydantic (forma de cada petición/respuesta)
│
├── frontend/                     # Interfaz web (HTML/CSS/JS plano, sin frameworks)
│   ├── index.html / script.js / style.css   # Chat del estudiante
│   ├── panel.html / panel.js / panel.css    # Panel de atención (asesores/general)
│   ├── root.html / root.js / root.css       # Panel de administración (root)
│   ├── admin-shared.js                      # Utilidades y helpers compartidos entre root.js y panel.js
│   ├── branding/logo.png                    # Logo de la institución (subido desde /root, dinámico)
│   └── favicon-*.png, apple-touch-icon.png  # Ícono de la app (fijo, no depende de la institución)
│
├── documents/                    # Documentos fuente que usa el chatbot para responder
│   ├── *_EJEMPLO.*                          # Documentos de ejemplo (reemplazar por los reales)
│   ├── web-*.txt                            # Páginas indexadas por un rastreo de sitio web (nombre derivado de la URL)
│   └── faq_generadas_*.txt                  # Generados automáticamente al aceptar una FAQ sugerida
│
├── docs/                         # Documentación del proyecto (este archivo vive aquí)
│   ├── manual-usuario.md                    # Cómo usar el sistema (estudiante/asesor/general/root)
│   ├── casos-de-uso.md                      # Catálogo de casos de uso por actor, incluidos los automáticos
│   ├── diagramas-de-secuencia.md            # Los mismos mecanismos reales, en diagramas de secuencia
│   ├── diagrama-de-clases.md                # Modelo de datos persistente y objetos en memoria, en diagramas de clases
│   ├── exposicion-guia.md                   # Guion y material de apoyo para sustentar el proyecto
│   ├── decision-uso-de-groq.md              # Por qué se eligió Groq como proveedor del LLM
│   ├── decision-modelo-embeddings.md        # Por qué ese modelo de embeddings y no otro
│   ├── notas-mejora-documentos.md           # Hallazgos para un futuro proceso de mejora
│   ├── analisis-comparativo-chatbots.md     # RAG frente a un chatbot de reglas o un LLM sin documentos
│   ├── stack-tecnologico.md                 # Resumen de tecnologías, para exponer
│   ├── estructura-del-proyecto.md           # Este documento
│   ├── analisis-capacidad-500-documentos.md # Viabilidad con 500 documentos indexados
│   ├── instalacion-linux.md                 # Guía de instalación en un servidor Linux por SSH
│   ├── flujo-chat-en-vivo.md                # Paso a paso de una pregunta hasta la respuesta
│   ├── flujo-escalamiento-y-atencion-humana.md  # Paso a paso del escalamiento a un asesor humano
│   ├── flujo-subida-documentos.md           # Paso a paso de subir/rastrear un documento hasta indexarlo
│   ├── conceptos-chunks-y-faiss.md          # Glosario: chunk, ingesta, FAISS, dónde vive cada cosa
│   ├── busqueda-lexica-bm25.md              # La segunda vía de recuperación (BM25, coincidencia exacta)
│   ├── conceptos-embeddings.md              # Cómo una frase se convierte en un vector, paso a paso
│   └── widget-embebible.md                  # Cómo funciona el chat embebido en otros sitios
│
├── scripts/                      # Herramientas de línea de comandos
│   ├── ingest.py                            # Reconstruye el índice vectorial completo
│   ├── create_root.py                       # Crea la primera cuenta root
│   └── run_server.ps1                       # Arranca el backend (PowerShell)
│
├── tests/                        # Pruebas automatizadas (pytest) -- una por área funcional
│   └── conftest.py                          # Configuración compartida de las pruebas
│
├── evaluation/                   # Evaluación académica del pipeline RAG
│   ├── test_questions.json                  # Preguntas de prueba con la respuesta esperada
│   ├── evaluate.py                          # Corre las preguntas contra el chatbot real y mide aciertos
│   └── last_report.json                     # Resultado de la última corrida (se genera, no se versiona)
│
├── .env / .env.example           # Configuración real / plantilla documentada de cada variable
├── .gitignore                    # Qué no se sube al repositorio (ver más abajo)
├── requirements.txt              # Dependencias de Python exactas del proyecto
├── pytest.ini                    # Configuración de pytest
├── ingestar.bat / iniciar.bat / instalar.bat   # Atajos de Windows (doble clic) para las tareas comunes
└── README.md                     # Documentación técnica principal del proyecto
```

## Qué NO está en el árbol de arriba (se genera solo, no se versiona)

Excluido por `.gitignore` porque son datos/artefactos que se recrean o son
sensibles, no código fuente:

| Carpeta/archivo | Por qué no se versiona |
|---|---|
| `venv/` | Entorno virtual de Python -- se recrea con `pip install -r requirements.txt`. |
| `vector_db/` | Índice FAISS -- se reconstruye con `scripts/ingest.py` a partir de `documents/`. |
| `history.db` | Base de datos con conversaciones reales de estudiantes -- dato sensible, no código. |
| `backups/` | Respaldos periódicos de `history.db` -- mismo motivo. |
| `.env` | Contiene la clave real de Groq -- nunca debe subirse a un repositorio. |
| `.pytest_cache/`, `__pycache__/` | Caché interna de Python/pytest. |
| `evaluation/last_report.json` | Resultado de la última evaluación -- se regenera cada corrida. |

## Cómo encajan las piezas (flujo de una pregunta)

1. El estudiante escribe en `frontend/script.js` → `POST /api/chat/stream`.
2. `app/api/routes.py` recibe la petición y llama a `chat_service.py`.
3. `chat_service.py` usa `retriever.py` (que usa `embeddings.py` +
   `vector_store.py`) para encontrar los fragmentos relevantes.
4. Con ese contexto, `llm.py` le pide la respuesta a Groq (pasando primero
   por `rate_limiter.py`).
5. La respuesta se guarda en `history.py` (SQLite) y se transmite de
   vuelta al navegador.

Cuando se escala a un humano, `ws_manager.py` avisa en tiempo real al
`frontend/panel.js` correspondiente; cuando el root gestiona el sistema,
`frontend/root.js` habla con las rutas de `routes.py` que a su vez usan
`admin_service.py`, `ingest_service.py` y `faq_service.py`.

Cuando root lanza un rastreo de sitio web desde `/root` (pestaña
Documentos), `crawl_job_service.py` corre en un hilo de fondo: usa
`web_crawler.py` para recorrer las páginas permitidas y reutiliza el
mismo pipeline de ingesta (`document_loader.py` no hace falta aquí --
`web_crawler.py` ya entrega texto plano -- pero sí `chunker.py`,
`embeddings.py` y `vector_store.py` vía `ingest_service.ingest_single_file`)
por cada página nueva o cambiada. Ver
[flujo-subida-documentos.md](flujo-subida-documentos.md) para el detalle
completo de esta vía alterna de ingesta.
