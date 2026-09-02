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

## 5. Tecnologías utilizadas

| Componente          | Tecnología                                         | Por qué                                                                 |
|----------------------|-----------------------------------------------------|--------------------------------------------------------------------------|
| Backend              | Python + FastAPI                                    | Simple, rápido, tipado con Pydantic, fácil de documentar (`/docs`).      |
| LLM                  | Groq API (`openai/gpt-oss-20b`)                     | Gratuito dentro del tier free, extremadamente rápido (~1000 tok/s), sin instalar nada localmente. |
| Embeddings           | Sentence Transformers (`paraphrase-multilingual-MiniLM-L12-v2`) | Local, gratuito, multilingüe (bueno para español), no depende de Groq. |
| Vector store         | FAISS                                                | Wheels precompilados para Windows (no requiere compilador C++, a diferencia de ChromaDB en Windows). |
| Frontend             | HTML + CSS + JS plano                                | Sin frameworks innecesarios; suficiente para una interfaz de chat clara. |

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

### 6.8. Acceder al chatbot

Abre tu navegador en: **http://localhost:8000**

La documentación interactiva de la API (Swagger) está disponible en:
http://localhost:8000/docs

## 7. Cómo agregar nuevos documentos

1. Copia el archivo (PDF, DOCX, TXT o XLSX) dentro de `documents/`.
2. Ejecuta `ingestar.bat` (o `python scripts/ingest.py`) para reconstruir el
   índice.
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

También existe el endpoint `POST /api/ingest`, que reconstruye el índice sin
necesidad de detener el servidor (útil para una futura interfaz de
administración, aunque para el uso normal se recomienda el script).

## 8. Configuración

Toda la configuración vive en `.env` (ver `.env.example` para la lista
completa y sus valores por defecto):

- `GROQ_API_KEY`, `GROQ_MODEL`: credenciales y modelo del LLM.
- `EMBEDDING_MODEL`: modelo local de embeddings.
- `TOP_K`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `SIMILARITY_THRESHOLD`: parámetros
  del pipeline RAG.
- `MAX_HISTORY_TURNS`: cuántos turnos de conversación previos se recuerdan.
- `BACKEND_HOST`, `BACKEND_PORT`: dónde corre el servidor.
- `DOCUMENTS_DIR`, `VECTOR_DB_DIR`, `MAX_FILE_SIZE_MB`: manejo de documentos.

## 9. Cómo ejecutar las pruebas

Pruebas automatizadas (ingestión, chunking, umbral de relevancia, API de
chat) — no requieren clave de Groq real, se simulan las llamadas al LLM:
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

## 10. Estructura del proyecto

```
chatbot/
├── app/
│   ├── main.py              # App FastAPI + servido del frontend
│   ├── config.py            # Configuración centralizada (.env)
│   ├── api/routes.py        # Endpoints: /api/chat, /api/chat/stream, /api/ingest, /api/health
│   ├── rag/                 # Núcleo del pipeline RAG
│   │   ├── document_loader.py   # Extracción de texto (PDF/DOCX/TXT/XLSX)
│   │   ├── chunker.py           # División en fragmentos con metadatos
│   │   ├── embeddings.py        # Embeddings locales (Sentence Transformers)
│   │   ├── vector_store.py      # Base vectorial FAISS
│   │   ├── retriever.py         # Búsqueda semántica + umbral de relevancia
│   │   └── llm.py               # Cliente Groq + prompt de sistema anti-alucinación
│   ├── services/
│   │   ├── chat_service.py      # Orquesta el pipeline completo + métricas
│   │   ├── ingest_service.py    # Lógica de ingestión (usada por CLI y API)
│   │   └── history.py           # Historial de conversación por sesión
│   └── models/schemas.py    # Contratos Pydantic de la API
├── scripts/ingest.py        # CLI de ingestión
├── evaluation/               # Evaluación académica del RAG
│   ├── test_questions.json
│   └── evaluate.py
├── tests/                     # Pruebas automatizadas (pytest)
├── frontend/                  # Interfaz web (HTML/CSS/JS)
├── documents/                 # Documentos fuente (PDF/DOCX/TXT/XLSX)
├── vector_db/                 # Índice FAISS (se genera, no se versiona)
├── .env.example
└── requirements.txt
```

## 11. Limitaciones conocidas

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
- El historial de conversación se guarda en memoria del proceso: si el
  backend se reinicia, se pierde (aceptable para una demo académica).
- FAISS con `IndexFlatIP` hace búsqueda exhaustiva (no aproximada); es
  perfectamente rápido para cientos o pocos miles de fragmentos, pero no
  está pensado para escalar a millones de documentos.
- El servicio depende de la disponibilidad de la API de Groq y de conexión
  a internet (los embeddings y la búsqueda sí son 100% locales).
- Los documentos incluidos en `documents/*_EJEMPLO.txt` son de ejemplo/
  ficticios y deben reemplazarse por los documentos oficiales reales antes
  de cualquier uso más allá de la demostración académica.

## 12. Seguridad y robustez implementadas

- Validación de extensión (`.pdf`, `.docx`, `.txt`) y tamaño máximo de
  archivo antes de procesarlo.
- Documentos corruptos o ilegibles se omiten individualmente durante la
  ingestión (con mensaje de error), sin detener el procesamiento del resto
  del lote.
- La clave de Groq nunca se expone al frontend ni se escribe en el código;
  vive solo en `.env` (excluido de git vía `.gitignore`).
- El prompt de sistema instruye explícitamente al modelo a ignorar
  instrucciones del usuario que intenten alterar su comportamiento o revelar
  el prompt (mitigación básica de prompt injection).
