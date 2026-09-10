# Diagramas de secuencia

Complemento visual de los documentos de flujo
([flujo-chat-en-vivo.md](flujo-chat-en-vivo.md),
[flujo-escalamiento-y-atencion-humana.md](flujo-escalamiento-y-atencion-humana.md),
[flujo-subida-documentos.md](flujo-subida-documentos.md),
[widget-embebible.md](widget-embebible.md)) y de
[casos-de-uso.md](casos-de-uso.md): los mismos mecanismos reales, en
formato de diagrama de secuencia (sintaxis [Mermaid](https://mermaid.js.org/syntax/sequenceDiagram.html),
se renderiza directamente en GitHub). Cada diagrama enlaza al documento
con la explicación completa en prosa -- aquí solo se anota lo
imprescindible para leerlo.

## Índice

1. [Pregunta al asistente virtual (chat en vivo)](#1-pregunta-al-asistente-virtual-chat-en-vivo)
2. [Escalar a atención humana](#2-escalar-a-atención-humana)
3. [El asesor responde](#3-el-asesor-responde)
4. [El asesor le pide ayuda al chatbot (sin enviar nada al estudiante)](#4-el-asesor-le-pide-ayuda-al-chatbot-sin-enviar-nada-al-estudiante)
5. [Redirección automática por SLA vencido](#5-redirección-automática-por-sla-vencido)
6. [Subir e indexar un documento](#6-subir-e-indexar-un-documento)
6a. [Indexar un sitio web (rastreo)](#6a-indexar-un-sitio-web-rastreo)
6b. [Marcar un documento como no descargable](#6b-marcar-un-documento-como-no-descargable)
7. [Generar y aceptar una sugerencia de FAQ](#7-generar-y-aceptar-una-sugerencia-de-faq)
8. [Detección de hostilidad y bloqueo temporal](#8-detección-de-hostilidad-y-bloqueo-temporal)
9. [Embeber el chat en un sitio externo (widget)](#9-embeber-el-chat-en-un-sitio-externo-widget)

---

## 1. Pregunta al asistente virtual (chat en vivo)

Ver [flujo-chat-en-vivo.md](flujo-chat-en-vivo.md) para el detalle de
cada paso con tiempos reales medidos, y
[busqueda-lexica-bm25.md](busqueda-lexica-bm25.md) para el mecanismo
completo (semántica + léxica + re-ranking) dentro de "Retriever".

```mermaid
sequenceDiagram
    actor Estudiante
    participant FE as "Frontend (script.js)"
    participant API as "chat_service.stream_answer"
    participant RAG as "Retriever (FAISS + BM25 + re-ranking)"
    participant Cache as "answer_cache_service"
    participant Groq
    participant DB as "SQLite (turns, chat_metrics)"

    Estudiante->>FE: Escribe una pregunta
    FE->>API: POST /api/chat/stream
    API->>API: needs_human(session_id)? -> No
    API->>RAG: retrieve_context(pregunta)
    RAG-->>API: fragmentos relevantes (sin Groq -- el re-ranking es el costo real)
    opt sin resultados, o seguimiento corto con historial
        API->>Groq: reformula/condensa la pregunta (rewrite_query_variations o condense_query_for_search)
        Groq-->>API: variante(s)
        API->>RAG: reintenta con la mejor variante
        RAG-->>API: fragmentos relevantes (o los mismos de antes, si no mejora)
    end
    API-->>FE: SSE "meta" {sources} (preliminar -- el paso "done" la reemplaza)
    API->>Cache: try_get_cached_answer(context_hash)
    alt hay respuesta cacheada para este contexto
        Cache-->>API: texto ya generado
        API-->>FE: SSE "delta" {text} (de una sola vez)
    else sin caché
        API->>Groq: chat.completions.create(stream=True)
        loop cada fragmento de texto
            Groq-->>API: delta
            API-->>FE: SSE "delta" {text}
            FE-->>Estudiante: repinta la burbuja (markdown)
        end
        API->>Cache: maybe_store_answer(context_hash, respuesta)
    end
    API->>API: extract_used_sources(respuesta) -- separa FUENTES_USADAS, filtra las fuentes
    API->>DB: record_chat_metrics(..., cache_hit) + append_turn
    API-->>FE: SSE "done" {sources filtradas, suggestions, metrics}
    Note over FE: reemplaza las fuentes de "meta" por las de "done"
```

---

## 2. Escalar a atención humana

Ver [flujo-escalamiento-y-atencion-humana.md, sección 1](flujo-escalamiento-y-atencion-humana.md#1-el-estudiante-escala----post-apiescalate).

```mermaid
sequenceDiagram
    actor Estudiante
    participant FE as "Frontend (script.js)"
    participant API as "POST /api/escalate"
    participant LLM as "Groq (classify_department)"
    participant DB as "SQLite (session_meta)"
    participant WS as "ws_manager"
    participant Panel as "Panel del asesor"

    Estudiante->>FE: "Solicitar atención humana" + nombre/correo/teléfono
    FE->>API: POST /api/escalate
    API->>LLM: classify_department(última pregunta, dependencias)
    LLM-->>API: dependencia_id (o None si falla/no hay dependencias)
    API->>DB: escalate_session (needs_human=1, escalated_at)
    API->>WS: broadcast_to_dependencia("escalated")
    WS-->>Panel: evento en tiempo real
    API->>API: is_within_horario(dependencia_id)?
    alt fuera de horario
        API-->>FE: within_horario=false + horario_texto
        FE-->>Estudiante: "no hay atención ahora, quedó guardada tu pregunta"
    else dentro de horario
        API-->>FE: within_horario=true
        FE-->>Estudiante: "tu pregunta fue escalada a un asesor"
    end
    FE->>WS: abre WS /api/ws/chat/{session_id}
```

---

## 3. El asesor responde

El mismo mecanismo aplica a "¿Necesita algo más?" (`ask-continue`), con
un texto fijo en vez del mensaje libre. Ver
[flujo-escalamiento-y-atencion-humana.md, secciones 2 y 6](flujo-escalamiento-y-atencion-humana.md#2-el-asesor-responde----post-adminsessionsidreply)
para las reglas de permiso y el detalle de `_advisor_label`.

```mermaid
sequenceDiagram
    actor Asesor
    participant Panel as "Panel (panel.js)"
    participant API as "POST /admin/sessions/{id}/reply"
    participant DB as "SQLite (admin_messages)"
    participant WS as "ws_manager"
    participant OtrosAsesores as "Otros asesores + general"
    actor Estudiante

    Asesor->>Panel: Escribe respuesta y presiona Enviar
    Panel->>API: POST /reply {message}
    API->>API: _ensure_admin_can_act_on_session
    API->>API: _advisor_label(identity) = "Nombre" o "Nombre · Dependencia"
    API->>DB: add_admin_message(sender="advisor", sender_name=...)
    API->>WS: broadcast_to_dependencia(advisor_message)
    WS-->>OtrosAsesores: eco en tiempo real (visibilidad, no acción)
    API->>WS: broadcast_to_session(advisor_message)
    WS-->>Estudiante: burbuja con el nombre real del asesor
```

---

## 4. El asesor le pide ayuda al chatbot (sin enviar nada al estudiante)

Ver [flujo-escalamiento-y-atencion-humana.md, sección 3](flujo-escalamiento-y-atencion-humana.md#3-herramienta-de-apoyo-del-asesor----post-adminsessionsidask-bot).

```mermaid
sequenceDiagram
    actor Asesor
    participant Panel as "Panel (panel.js)"
    participant API as "POST /admin/sessions/{id}/ask-bot"
    participant RAG as "Retriever + FAISS"
    participant Groq

    Asesor->>Panel: (opcional) reescribe la pregunta del estudiante
    Asesor->>Panel: "Preguntar al asistente"
    Panel->>API: POST /ask-bot {question}
    API->>RAG: retrieve_context(question)
    RAG-->>API: fragmentos relevantes
    API->>Groq: genera una respuesta sugerida
    Groq-->>API: respuesta + fuentes
    API-->>Panel: respuesta sugerida (no se guarda, no se transmite)
    alt Asesor usa la respuesta
        Panel->>Panel: copia el texto al campo de respuesta
        Note over Panel,Asesor: de aquí en adelante sigue el diagrama 3 (reply)
    else Asesor descarta
        Panel->>Panel: borra la sugerencia sin usarla
    end
```

---

## 5. Redirección automática por SLA vencido

Reusa exactamente el mismo `_perform_reassignment` que la redirección
manual del panel ("Redirigir a..."). Ver
[flujo-escalamiento-y-atencion-humana.md, sección 5](flujo-escalamiento-y-atencion-humana.md#5-redirigirreclamar-una-conversación----_perform_reassignment).

```mermaid
sequenceDiagram
    participant Job as "_auto_escalation_loop (background)"
    participant DB as "SQLite (session_meta)"
    participant WS as "ws_manager"
    participant DepAnterior as "Panel dependencia anterior"
    participant General as "Panel del general"
    actor Estudiante

    loop cada AUTO_ESCALATION_CHECK_INTERVAL_SECONDS
        Job->>DB: find_unattended_sessions(timeout=5 min)
        DB-->>Job: sesiones sin first_response_at
        alt hay sesiones vencidas
            Job->>DB: reassign_dependencia(session_id, None)
            Job->>WS: broadcast_to_dependencia (anterior)
            WS-->>DepAnterior: "reassigned" (desaparece de su lista)
            Job->>WS: broadcast_to_dependencia(None) (bandeja general)
            WS-->>General: "reassigned" (aparece en la suya)
            Job->>WS: broadcast_to_session
            WS-->>Estudiante: "seguimos gestionando tu solicitud"
        end
    end
```

---

## 6. Subir e indexar un documento

Ver [flujo-subida-documentos.md](flujo-subida-documentos.md) para el
detalle de conversión PDF/DOCX→TXT, paginación por formato y por qué el
XLSX no se aplana a texto plano.

```mermaid
sequenceDiagram
    actor Admin as "Root / Asesor / General"
    participant FE as "root.js / panel.js"
    participant API as "_upload_document"
    participant Loader as "document_loader"
    participant Chunker as "chunker"
    participant Emb as "embeddings (local)"
    participant FAISS as "vector_store (FAISS)"

    Admin->>FE: Sube archivo (PDF/TXT/DOCX/XLSX)
    FE->>API: POST /admin|root/documents (multipart)
    API->>API: valida extensión y tamaño
    alt PDF o DOCX
        API->>Loader: extrae texto
        Loader-->>API: texto plano
        API->>API: guarda como .txt, borra el original
    else TXT o XLSX
        API->>API: guarda tal cual
    end
    API->>API: set_document_dependencia(archivo, dependencia_id)
    API->>Loader: load_document(archivo final)
    Loader-->>API: "páginas" (1 por hoja de PDF, 1 por hoja de Excel, etc.)
    API->>Chunker: chunk_document(páginas)
    Chunker-->>API: fragmentos (texto normal por oración, Excel por fila)
    API->>Emb: embed_texts(fragmentos)
    Emb-->>API: vectores normalizados (384 dim, sin llamar a Groq)
    API->>FAISS: add_chunks(vectores + metadatos)
    FAISS-->>API: persistido en index.faiss + metadata.json
    API-->>FE: IngestResponse (fragmentos creados, nombre final)
    Note over FAISS: el chatbot ya puede citar este documento<br/>desde la siguiente pregunta, sin pasos extra
```

Este mismo tramo (`Loader` opcional → `Chunker` → `Emb` → `FAISS`) es
justo el que reutiliza el rastreo de sitio web (diagrama 6a) por cada
página nueva o cambiada -- no es un pipeline aparte, es el mismo con
otra fuente de entrada.

---

## 6a. Indexar un sitio web (rastreo)

Ver [flujo-subida-documentos.md, sección 8](flujo-subida-documentos.md#8-vía-alterna-rastreo-automático-de-un-sitio-web)
y CU-31a/CU-31b/CU-38a en [casos-de-uso.md](casos-de-uso.md). Exclusivo
de root.

```mermaid
sequenceDiagram
    actor Root
    participant FE as "root.js (modal + polling)"
    participant API as "POST /root/crawl-site"
    participant Job as "crawl_job_service (hilo de fondo)"
    participant Crawler as "web_crawler.crawl_site (BFS)"
    participant Hash as "document_hashes (SHA-256)"
    participant Ingest as "mismo pipeline del diagrama 6"
    participant Pending as "SQLite (crawl_pending_files)"

    Root->>FE: URL inicial, ruta permitida, profundidad, máx. páginas
    FE->>API: POST /root/crawl-site
    API->>Job: start_crawl_job(...) (hilo daemon)
    API-->>FE: {job_id} (responde de inmediato, no espera)
    loop por cada página encontrada (respeta robots.txt y dominio+ruta)
        Job->>Crawler: siguiente página permitida
        alt es PDF/DOCX/XLSX enlazado
            Crawler-->>Job: content_bytes (no se indexa solo)
            Job->>Pending: guarda url/seed_url/dependencia_id (UNIQUE en url)
        else es una página HTML
            Crawler-->>Job: texto (ya extraído por trafilatura)
            Job->>Hash: ¿hash igual al de la última vez para este archivo?
            alt sin cambios desde el último rastreo
                Hash-->>Job: mismo hash -- se salta (pages_unchanged++)
            else contenido nuevo o cambiado
                Job->>Ingest: ingest_single_file (chunking + embeddings + FAISS)
                Job->>Job: set_document_downloadable(False) + set_document_source_url
                Job->>Hash: registra el hash nuevo
                Ingest-->>Job: pages_indexed++
            end
        end
        FE->>API: GET /root/crawl-site/{job_id} (polling cada 1.5s)
        API-->>FE: progreso (indexadas, sin cambios, fallidas, url actual)
    end
    opt Root cancela a mitad de camino
        FE->>API: POST /root/crawl-site/{job_id}/cancel
        API->>Job: cancel_requested = true
        Note over Job: termina después de la página en curso, no de golpe
    end
    Note over FE,Root: al cerrar el modal, el rastreo sigue corriendo en el servidor
```

---

## 6b. Marcar un documento como no descargable

Ver CU-18a/CU-23/CU-31 en [casos-de-uso.md](casos-de-uso.md).

```mermaid
sequenceDiagram
    actor Admin as "Root / General / Dependencia (dueño)"
    participant FE as "root.js / panel.js"
    participant API as "PUT /root|admin/documents/{filename}/downloadable"
    participant DB as "SQLite (document_dependencias.downloadable)"
    actor Estudiante

    Admin->>FE: Desmarca el checkbox "Descargable"
    FE->>API: PUT .../downloadable {downloadable: false}
    alt rol dependencia y el documento no es suyo
        API-->>FE: 403 (no se toca nada)
    else autorizado
        API->>DB: set_document_downloadable(filename, false)
        Note over DB: no reingesta -- el flag se consulta al vuelo,<br/>no queda "horneado" en los metadatos del chunk
        API-->>FE: 200 OK
    end
    Note over Estudiante: la próxima vez que este documento aparezca<br/>como fuente, no se le ofrece botón de descarga<br/>(sigue siendo usado para responder igual)
```

---

## 7. Generar y aceptar una sugerencia de FAQ

Ver CU-32 y CU-37 en [casos-de-uso.md](casos-de-uso.md).

```mermaid
sequenceDiagram
    actor Asesor
    participant API as "resolve_session_as_advisor"
    participant LLM as "Groq (generate_faq_candidate)"
    participant DB as "SQLite (faq_candidates)"
    actor Root
    participant Ingest as "ingest_service (reindexar)"

    Asesor->>API: POST /admin/sessions/{id}/resolve
    API->>API: _maybe_generate_faq_candidate
    API->>LLM: reescribe pregunta+respuesta en formato FAQ
    LLM-->>API: propuesta (o nada, si no aplica)
    API->>API: compara contra FAQ ya aceptadas (evita duplicados)
    API->>DB: guarda la propuesta como "pending"
    Note over Root: más tarde, en /root
    Root->>DB: lee faq_candidates pendientes
    alt Root acepta
        Root->>Ingest: agrega al documento de FAQ de la dependencia
        Ingest-->>Ingest: reindexa (mismo mecanismo del diagrama 6)
        Note over Ingest: el chatbot puede responder esa pregunta desde ahora
    else Root rechaza
        Root->>DB: elimina la propuesta
    end
```

---

## 8. Detección de hostilidad y bloqueo temporal

Ver `app/services/hostility_service.py` y CU-39 en
[casos-de-uso.md](casos-de-uso.md).

```mermaid
sequenceDiagram
    actor Estudiante
    participant API as "chat_service"
    participant Hostility as "hostility_service"
    participant DB as "SQLite (hostility_keywords, session strikes)"

    Estudiante->>API: envía un mensaje
    API->>Hostility: contains_hostile_language(mensaje)
    Hostility->>DB: compara contra la lista de palabras/frases
    DB-->>Hostility: coincidencia (con límite de palabra, no substring)
    alt contiene lenguaje hostil
        Hostility->>DB: +1 aviso para esta session_id
        alt llegó a 3 avisos seguidos
            Hostility-->>API: bloquear sesión (2 horas)
            API-->>Estudiante: sesión bloqueada temporalmente
        else todavía no
            API-->>Estudiante: continúa, pero queda contabilizado
        end
    else mensaje normal
        API->>API: sigue el flujo normal (diagrama 1)
    end
```

---

## 9. Embeber el chat en un sitio externo (widget)

Ver [widget-embebible.md](widget-embebible.md) para la explicación
completa de por qué `frame-ancestors` es una restricción del navegador,
no del backend.

```mermaid
sequenceDiagram
    actor Visitante as "Visitante del sitio anfitrión"
    participant Sitio as "Sitio anfitrión"
    participant Loader as "widget-loader.js"
    participant Backend as "Backend del chatbot"

    Sitio->>Loader: <script src=".../widget-loader.js">
    Loader->>Loader: calcula su propio origen
    Loader->>Sitio: inyecta el botón flotante
    Visitante->>Loader: hace clic en el botón
    Loader->>Backend: crea <iframe src=".../widget">
    Backend->>Backend: arma CSP frame-ancestors (orígenes autorizados en ese instante)
    Backend-->>Loader: HTML de /widget + cabecera CSP
    alt el origen del Sitio está autorizado
        Loader-->>Visitante: el iframe carga (el navegador lo permite)
        Visitante->>Backend: usa el chat normalmente (mismo origen que /widget)
    else el origen NO está autorizado
        Note over Loader: el navegador bloquea el iframe por CSP
        Loader-->>Visitante: no se ve el chat
    end
```
