# Chatbot Facultad de Ingeniería — Asistente RAG

Proyecto académico para la asignatura de Inteligencia Artificial: un chatbot
conversacional que responde preguntas sobre reglamentos, calendario
académico, matrículas, requisitos de grado y demás procesos de la Facultad
de Ingeniería, basándose **exclusivamente** en documentos oficiales cargados
por el administrador.

## 1. Qué es el proyecto

Un asistente web que estudiantes pueden usar para preguntar, en lenguaje
natural, cosas como "¿cuáles son los requisitos para graduarme?" o "¿puedo
cancelar una asignatura?", y recibir una respuesta fundamentada en los
documentos reales de la facultad, con las fuentes citadas (documento y
página).

## 2. Qué problema resuelve

Los estudiantes normalmente deben leer reglamentos extensos o preguntar
directamente en las oficinas administrativas para resolver dudas sencillas.
Este chatbot centraliza esa información y permite consultarla de forma
conversacional, sin inventar respuestas cuando la información no está
disponible.

## 3. Qué es RAG (Retrieval-Augmented Generation)

En vez de que el modelo de lenguaje (LLM) responda solo con lo que
"recuerda" de su entrenamiento (lo cual puede llevar a alucinaciones), el
sistema primero **busca** los fragmentos de texto más relevantes dentro de
los documentos oficiales (usando búsqueda semántica por embeddings), y luego
le **entrega esos fragmentos como contexto** al LLM junto con la pregunta,
pidiéndole que responda solo con base en ese contexto. Así la respuesta
queda "anclada" (grounded) en información real y verificable.

## 4. Arquitectura

```
Usuario
  ↓
Frontend web (HTML/CSS/JS)
  ↓
Backend FastAPI
  ↓
Embedding de la pregunta (Sentence Transformers, local)
  ↓
Búsqueda semántica en FAISS (base vectorial local)
  ↓
Filtro por umbral de similitud
  ↓
Construcción del contexto (fragmentos + fuente + página)
  ↓
LLM en la nube vía Groq API (openai/gpt-oss-20b)
  ↓
Respuesta + fuentes citadas
  ↓
Usuario
```

El flujo completo (carga → chunking → embeddings → vector store → búsqueda →
contexto → LLM → respuesta con fuentes) está implementado de extremo a
extremo; no es un chatbot que reenvíe la pregunta directamente al LLM.

Cuando el chatbot no tiene información suficiente, el estudiante puede pedir
hablar con un humano: la conversación se **escala** a un panel de
administración con roles y ruteo automático por dependencia (ver sección 7).

## 5. Tecnologías utilizadas

| Componente          | Tecnología                                         | Por qué                                                                 |
|----------------------|-----------------------------------------------------|--------------------------------------------------------------------------|
| Backend              | Python + FastAPI                                    | Simple, rápido, tipado con Pydantic, fácil de documentar (`/docs`).      |
| LLM                  | Groq API (`openai/gpt-oss-20b`)                     | Gratuito dentro del tier free, extremadamente rápido (~1000 tok/s), sin instalar nada localmente. |
| Embeddings           | Sentence Transformers (`paraphrase-multilingual-MiniLM-L12-v2`) | Local, gratuito, multilingüe (bueno para español), no depende de Groq. |
| Vector store         | FAISS                                                | Wheels precompilados para Windows (no requiere compilador C++, a diferencia de ChromaDB en Windows). |
| Frontend             | HTML + CSS + JS plano                                | Sin frameworks innecesarios; suficiente para una interfaz de chat clara. |
| Autenticación admin  | bcrypt + tokens de sesión propios                    | Sin dependencias externas de OAuth/JWT; suficiente para un panel interno con pocos administradores. |
| Tiempo real (panel)  | WebSockets (FastAPI/Starlette)                       | Notifica al instante nuevos chats, respuestas y reasignaciones sin hacer polling. |

### Por qué FAISS y no ChromaDB

El enunciado permitía elegir entre ChromaDB o FAISS. Se intentó primero con
ChromaDB, pero su dependencia `chroma-hnswlib` **no distribuye wheels
precompilados para Windows** y requiere Microsoft Visual C++ Build Tools
para compilarse desde código fuente — una instalación pesada y compleja para
un proyecto académico. FAISS (`faiss-cpu`) sí distribuye wheels
precompilados para Windows/Python 3.13, por lo que `pip install` funciona
sin instalar herramientas adicionales.

### Por qué `openai/gpt-oss-20b` como modelo de Groq

El catálogo de modelos de Groq cambia con el tiempo (los modelos Llama que
antes eran el estándar ya fueron retirados). Antes de fijar un modelo se
consultó la lista real de modelos disponibles vía la API
(`client.models.list()`), no solo la documentación web. `openai/gpt-oss-20b`
es un modelo activo de producción, con 131K de contexto, muy alta velocidad
(~1000 tok/s) y disponible en el nivel gratuito. Si Groq vuelve a cambiar su
catálogo, verifica los modelos vigentes en
https://console.groq.com/docs/models o ejecutando `client.models.list()`.

### Por qué Groq ofrece uso gratuito

Groq (la empresa) no debe confundirse con "Grok" de xAI: es una compañía de
hardware que diseñó un chip propio llamado **LPU** (Language Processing
Unit), especializado en generar tokens de modelos de lenguaje mucho más
rápido que las GPUs tradicionales. El nivel gratuito de su API (GroqCloud)
no es una promoción temporal ni caridad, sino una estrategia de adopción
típica de empresas de hardware/infraestructura:

- Sirve como demostración de la velocidad de su chip: cuesta relativamente
  poco atender consultas de bajo volumen en hardware que ya está construido,
  a cambio de que desarrolladores prueben la plataforma y la recomienden.
- El negocio real de Groq está en clientes de alto volumen, que pagan por
  planes superiores o contratan directamente su infraestructura.
- El nivel gratuito **no es ilimitado**: tiene límites de velocidad
  (peticiones por minuto, tokens por minuto/día). Un proyecto académico de
  bajo tráfico cabe cómodamente dentro de esos límites, pero un uso en
  producción con muchos usuarios simultáneos probablemente los superaría y
  necesitaría pasar a un plan pago.
- Estas condiciones pueden cambiar con el tiempo; verifica los límites
  vigentes en https://console.groq.com/docs/rate-limits antes de asumir que
  se mantendrán igual.

## 6. Instalación (Windows, paso a paso)

### 6.1. Instalar Python

1. Descarga Python 3.11 o superior desde https://www.python.org/downloads/
2. Durante la instalación, marca la casilla **"Add python.exe to PATH"**.
3. Verifica la instalación abriendo una terminal (PowerShell) y ejecutando:
   ```
   py --version
   ```

### 6.2. Obtener una clave de Groq (gratis)

1. Crea una cuenta en https://console.groq.com
2. Ve a **API Keys** (https://console.groq.com/keys) y genera una clave.
3. Guárdala; la necesitarás en el paso 6.4.

### 6.3. Instalar dependencias del proyecto

Opción rápida: haz doble clic en **`instalar.bat`** (en la raíz del
proyecto). Esto crea el entorno virtual, instala todas las dependencias y
genera el archivo `.env` a partir de `.env.example`.

Opción manual (PowerShell, desde la carpeta del proyecto):
```powershell
py -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

> La primera instalación puede tardar varios minutos porque descarga
> PyTorch (usado internamente por Sentence Transformers).

### 6.4. Configurar la clave de Groq

Abre el archivo `.env` (creado en el paso anterior) con un editor de texto y
coloca tu clave:
```
GROQ_API_KEY=tu_clave_aqui
```

### 6.5. Agregar documentos

Coloca tus archivos PDF, DOCX, TXT o XLSX dentro de la carpeta `documents/`. El
proyecto ya incluye 3 documentos de **ejemplo** (marcados como
`_EJEMPLO`) para poder probar el sistema de inmediato; reemplázalos o
complétalos con los documentos oficiales reales de la facultad.

### 6.6. Construir el índice (ingestión)

Doble clic en **`ingestar.bat`**, o desde la terminal:
```powershell
venv\Scripts\python.exe scripts\ingest.py
```
Esto lee todos los documentos, los divide en fragmentos, genera sus
embeddings (localmente) y construye la base vectorial FAISS en
`vector_db/`. Debes repetir este paso cada vez que agregues o cambies
documentos.

### 6.7. Iniciar el backend

Doble clic en **`iniciar.bat`**, o desde la terminal:
```powershell
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6.8. Crear la cuenta root

Antes de usar el panel de administración necesitas la primera cuenta
`root`:
```powershell
venv\Scripts\python.exe scripts\create_root.py
```
Pide un usuario (usa un correo electrónico, ej. `root@tudominio.com`) y una
contraseña por consola.

### 6.9. Acceder al chatbot y a los paneles

- Chat de estudiantes: **http://localhost:8000**
- Panel de atención (asesores/administradores): **http://localhost:8000/panel**
- Panel de administración root: **http://localhost:8000/root**

La documentación interactiva de la API (Swagger) está disponible en:
http://localhost:8000/docs

## 7. Panel de administración y sistema de roles

Además del chat para estudiantes, el proyecto incluye un panel de
administración completo con tres tipos de cuenta:

- **root** — no atiende chats. Administra la información de la institución
  (nombre, logo), crea y edita **dependencias** (facultades u oficinas) y sus
  administradores, sube y organiza documentos (etiquetándolos por
  dependencia) y revisa las preguntas frecuentes que el sistema propone
  automáticamente.
- **general** — administrador supervisor. Ve **todas** las conversaciones
  escaladas a un humano, sin importar a qué dependencia fueron asignadas,
  junto con el tiempo que llevan esperando respuesta. Puede leer cualquier
  conversación, pero solo puede responder/resolver las que reclame para sí
  mismo (redirigiéndolas hacia él) — sirve de respaldo cuando una dependencia
  no responde a tiempo o el sistema no logra clasificar la pregunta.
- **dependencia** — administrador de una sola dependencia (ej. "Facultad de
  Derecho", "Bienestar Universitario"). Solo ve y atiende las conversaciones
  asignadas a su propia dependencia.

### 7.1 Autenticación

Cada administrador tiene una cuenta real: usuario (en formato de correo
electrónico) + contraseña, hasheada con bcrypt. Al iniciar sesión se emite
un token de sesión opaco (no JWT), guardado en la tabla `admin_sessions` con
expiración — ya no existe un token compartido único para todos los
administradores. `scripts/create_root.py` crea la primera cuenta root; desde
ahí, ese root crea el resto de administradores.

### 7.2 Ruteo automático por dependencia (LLM)

Cuando un estudiante pide hablar con un humano (`POST /api/escalate`), un
LLM (Groq, modo JSON) decide a qué dependencia dirigir la conversación,
usando la descripción de cada dependencia (mientras más clara, mejor el
enrutamiento — se edita desde el panel root) y los documentos etiquetados
por dependencia que resultaron relevantes para esa pregunta, como pista
adicional de a quién pertenece el tema.

Si el LLM no logra clasificarla con confianza, la conversación queda sin
asignar y la atiende el administrador **general**. Cualquier administrador
puede además redirigir manualmente una conversación mal clasificada hacia
otra dependencia (o hacia sí mismo, si es el general).

### 7.3 SLA de 5 minutos y auto-escalación

Si una dependencia no responde una conversación asignada dentro de
`AUTO_ESCALATION_TIMEOUT_SECONDS` (5 minutos por defecto), un proceso en
segundo plano la redirige automáticamente al administrador general y
notifica al estudiante que su solicitud se sigue gestionando. El cronómetro
se reinicia con cada reasignación (manual o automática); se considera
"atendida" desde el primer mensaje que envía el asesor asignado.

### 7.4 Preguntas frecuentes generadas automáticamente

Cuando un asesor resuelve una conversación escalada que sí tuvo respuesta
suya, el sistema le pide a un LLM que reescriba la pregunta original y la
respuesta del asesor en formato de FAQ profesional, y la deja como una
propuesta pendiente de revisión. Desde la pestaña "Preguntas frecuentes" del
panel root se puede editar el texto sugerido y aceptarlo con un clic: al
aceptar, la entrada se agrega al archivo de FAQ de la dependencia
correspondiente (`documents/faq_generadas_dependencia_{id}.txt`, o
`faq_generadas_general.txt` si no tiene dependencia) y se reingesta
automáticamente.

### 7.5 Ingesta incremental

Subir, recategorizar o eliminar un documento, o aceptar una FAQ, ya no
reconstruye todo el índice vectorial desde cero: solo se calculan (o se
quitan) los embeddings del archivo afectado, dejando el resto del índice
intacto — el costo de cada cambio pequeño no crece junto con el volumen
total de documentos. La reconstrucción completa (`python scripts/ingest.py`
o `POST /api/ingest`) sigue disponible para reindexar todo el corpus cuando
haga falta (por ejemplo, tras cambiar `CHUNK_SIZE` o el modelo de
embeddings).

## 8. Cómo agregar nuevos documentos

**Desde el panel root** (recomendado): pestaña "Documentos" → subir
archivo, opcionalmente etiquetarlo con una dependencia. Se reingesta
automáticamente (solo ese archivo, ver 7.5).

**Manualmente por CLI**:
1. Copia el archivo (PDF, DOCX, TXT o XLSX) dentro de `documents/`.
2. Ejecuta `ingestar.bat` (o `python scripts/ingest.py`) para reconstruir el
   índice completo.
3. Reinicia el backend (`iniciar.bat`) si ya estaba corriendo, para que
   cargue el índice actualizado.

### Consejo: datos puntuales que quedan "enterrados"

Si un dato corto y específico (una ubicación, un teléfono, un correo) está
mezclado dentro de un documento largo con muchos otros temas, el chunking por
tamaño fijo puede agruparlo junto a contenido no relacionado y diluir su
similitud semántica — el chatbot podría no encontrarlo aunque sí esté en los
documentos. **No se soluciona bajando `SIMILARITY_THRESHOLD`** (eso deja
pasar también preguntas que deben rechazarse, como precios que no existen en
los documentos). La solución correcta es mantener esos datos puntuales como
su propio documento corto o en una sección claramente delimitada, en vez de
mezclarlos con contenido extenso de otro tema.

El endpoint `POST /api/ingest` (usado internamente por el botón de
reingesta manual del panel root) reconstruye el índice completo sin
necesidad de detener el servidor; para cambios de un solo documento, el
panel usa en cambio la ingesta incremental descrita en 7.5.

## 9. Configuración

Toda la configuración vive en `.env` (ver `.env.example` para la lista
completa y sus valores por defecto):

- `GROQ_API_KEY`, `GROQ_MODEL`: credenciales y modelo del LLM.
- `EMBEDDING_MODEL`: modelo local de embeddings.
- `TOP_K`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `SIMILARITY_THRESHOLD`: parámetros
  del pipeline RAG.
- `MAX_HISTORY_TURNS`: cuántos turnos de conversación previos se recuerdan.
- `HISTORY_BACKUP_DIR`, `HISTORY_BACKUP_INTERVAL_SECONDS`,
  `HISTORY_BACKUP_RETENTION`: respaldo periódico de `history.db`.
- `AUTO_ESCALATION_TIMEOUT_SECONDS`, `AUTO_ESCALATION_CHECK_INTERVAL_SECONDS`:
  SLA de auto-escalación al administrador general (ver 7.3).
- `BACKEND_HOST`, `BACKEND_PORT`: dónde corre el servidor.
- `DOCUMENTS_DIR`, `VECTOR_DB_DIR`, `MAX_FILE_SIZE_MB`: manejo de documentos.
- `ALLOWED_ORIGINS`: orígenes permitidos por CORS.
- `CHAT_RATE_LIMIT_MAX`/`_WINDOW_SECONDS`: límite de peticiones al chat por IP.
- `LOGIN_RATE_LIMIT_MAX`/`_WINDOW_SECONDS`: límite de intentos de login por IP
  (freno a fuerza bruta).

## 10. Cómo ejecutar las pruebas

Pruebas automatizadas (ingestión, chunking, umbral de relevancia, API de
chat, autenticación y roles, ruteo por dependencia, SLA/auto-escalación,
FAQ automáticas) — no requieren clave de Groq real, se simulan las llamadas
al LLM:
```powershell
venv\Scripts\python.exe -m pytest
```

Evaluación académica del RAG (sí requiere `GROQ_API_KEY` real y el índice ya
construido): ejecuta un set de preguntas de prueba y verifica si el sistema
recupera la fuente correcta, responde con las palabras clave esperadas, y
reconoce cuándo no tiene información suficiente:
```powershell
venv\Scripts\python.exe evaluation\evaluate.py
```
El resultado detallado se guarda en `evaluation/last_report.json` y es útil
para mostrar en la sustentación que el proceso RAG realmente funciona.

## 11. Estructura del proyecto

```
chatbot/
├── app/
│   ├── main.py              # App FastAPI + servido del frontend + tareas de fondo (backups, SLA)
│   ├── config.py            # Configuración centralizada (.env)
│   ├── api/
│   │   ├── routes.py        # Todos los endpoints: chat, escalación, panel admin, root, FAQ
│   │   └── security.py      # Sesiones de admin, control de acceso por rol, rate limiting
│   ├── rag/                 # Núcleo del pipeline RAG
│   │   ├── document_loader.py   # Extracción de texto (PDF/DOCX/TXT/XLSX)
│   │   ├── chunker.py           # División en fragmentos con metadatos
│   │   ├── embeddings.py        # Embeddings locales (Sentence Transformers)
│   │   ├── vector_store.py      # Base vectorial FAISS (add/remove por documento)
│   │   ├── retriever.py         # Búsqueda semántica + umbral de relevancia
│   │   └── llm.py               # Cliente Groq: respuesta, clasificación de dependencia, FAQ
│   ├── services/
│   │   ├── chat_service.py      # Orquesta el pipeline completo + métricas
│   │   ├── ingest_service.py    # Ingestión completa e incremental (CLI y API)
│   │   ├── history.py           # Historial de conversación, sesiones, dependencias
│   │   ├── admin_service.py     # Autenticación, CRUD de administradores/dependencias
│   │   ├── faq_service.py       # Propuestas de FAQ auto-generadas
│   │   └── ws_manager.py        # WebSockets del panel (por rol/dependencia) y del chat
│   └── models/schemas.py    # Contratos Pydantic de la API
├── scripts/
│   ├── ingest.py             # CLI de ingestión completa
│   └── create_root.py        # Bootstrap de la primera cuenta root
├── evaluation/               # Evaluación académica del RAG
│   ├── test_questions.json
│   └── evaluate.py
├── tests/                     # Pruebas automatizadas (pytest)
├── frontend/
│   ├── index.html/script.js/style.css   # Chat de estudiantes
│   ├── panel.html/panel.js/panel.css    # Panel de atención (asesores/admins)
│   └── root.html/root.js/root.css       # Panel de administración root
├── documents/                 # Documentos fuente (PDF/DOCX/TXT/XLSX) + FAQ generadas
├── vector_db/                 # Índice FAISS (se genera, no se versiona)
├── backups/                    # Respaldos periódicos de history.db (no se versiona)
├── .env.example
└── requirements.txt
```

## 12. Limitaciones conocidas

- Los PDF escaneados como imagen (sin texto seleccionable) no pueden
  procesarse; se necesitaría OCR, que está fuera del alcance de este
  proyecto.
- Solo se soporta el formato Excel moderno `.xlsx`. Los archivos `.xls`
  antiguos (Excel 97-2003) deben guardarse primero como `.xlsx`.
- En los archivos Excel, cada fila se indexa como su propio fragmento (no se
  agrupan varias filas juntas), para que cada registro se pueda recuperar
  de forma precisa. Esto significa que una tabla con miles de filas genera
  miles de fragmentos; es apropiado para horarios o pensum, no para bases
  de datos masivas.
- El historial de conversación, las sesiones, los administradores y las
  dependencias se guardan en SQLite (`history.db`, con respaldo periódico en
  `backups/`); solo las conexiones WebSocket del panel viven en memoria del
  proceso, así que reiniciar el backend no pierde datos pero sí desconecta
  momentáneamente a los administradores conectados en ese instante.
- El seguimiento de conexiones WebSocket es en memoria de un solo proceso:
  el proyecto no está pensado para correr varias instancias del backend
  detrás de un balanceador de carga sin adaptar `ws_manager.py`.
- FAISS con `IndexFlatIP` hace búsqueda exhaustiva (no aproximada); es
  perfectamente rápido para cientos o pocos miles de fragmentos, pero no
  está pensado para escalar a millones de documentos.
- El servicio depende de la disponibilidad de la API de Groq y de conexión
  a internet (los embeddings y la búsqueda sí son 100% locales); la
  clasificación de dependencia y la generación de FAQ también dependen de
  Groq y son best-effort (si fallan, la conversación queda sin clasificar o
  simplemente no se genera la propuesta de FAQ, sin romper el flujo).
- Los documentos incluidos en `documents/*_EJEMPLO.txt` son de ejemplo/
  ficticios y deben reemplazarse por los documentos oficiales reales antes
  de cualquier uso más allá de la demostración académica.

## 13. Seguridad y robustez implementadas

- Validación de extensión (`.pdf`, `.docx`, `.txt`, `.xlsx`) y tamaño máximo
  de archivo antes de procesarlo.
- Documentos corruptos o ilegibles se omiten individualmente durante la
  ingestión (con mensaje de error), sin detener el procesamiento del resto
  del lote.
- La clave de Groq nunca se expone al frontend ni se escribe en el código;
  vive solo en `.env` (excluido de git vía `.gitignore`).
- El prompt de sistema instruye explícitamente al modelo a ignorar
  instrucciones del usuario que intenten alterar su comportamiento o revelar
  el prompt (mitigación básica de prompt injection).
- Cuentas de administrador reales (usuario en formato de correo + contraseña
  hasheada con bcrypt), sin contraseñas ni tokens compartidos entre
  administradores.
- Control de acceso por rol y por dependencia en cada endpoint del panel: un
  administrador de dependencia no puede leer ni actuar sobre conversaciones
  de otra dependencia; el rol root no tiene acceso a los chats.
- Límite de peticiones (rate limiting) tanto en `/api/chat` (evitar agotar
  la cuota de Groq) como en `/api/auth/login` (frenar fuerza bruta sobre
  contraseñas).
