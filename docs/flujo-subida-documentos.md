# Flujo de subida de un documento (TXT, PDF, DOCX, XLSX)

Este documento describe, paso a paso, qué pasa desde que un administrador
sube un archivo (desde `/root` o desde `/panel`) hasta que su contenido
queda disponible para que el chatbot lo use al responder preguntas. Sirve
como referencia de arquitectura -- no implica ningún cambio de código.

## 1. Navegador -- formulario de subida

- **Root** (`root.js`, pestaña Documentos): sube a `POST /api/root/documents`,
  puede elegir cualquier dependencia (o dejarlo general/compartido).
- **Panel** (`panel.js`, pestaña Documentos): sube a `POST /api/admin/documents`.
  Un administrador `general` puede elegir dependencia igual que root; uno de
  `dependencia` no ve ese selector -- el backend le fuerza siempre la suya.
- En ambos casos es un `FormData` (multipart) con el archivo y, opcionalmente,
  `dependencia_id`.

## 2. Ruta del backend -- `app/api/routes.py`

Las rutas de subida (`upload_document_route` para root, y la de
`/admin/documents` para panel) solo verifican el rol/alcance de quien sube
y qué `dependencia_id` le permiten usar; ambas delegan el trabajo real a la
misma función compartida: **`_upload_document(content, filename, dependencia_id)`**.

## 3. `_upload_document` -- validación y conversión

1. Limpia el nombre de archivo (descarta cualquier ruta de directorio) y
   valida la extensión contra `settings.ALLOWED_EXTENSIONS` (`.txt`, `.pdf`,
   `.docx`, `.xlsx`) y el tamaño contra `settings.MAX_FILE_SIZE_MB`.
2. Escribe el archivo tal cual llegó en `DOCUMENTS_DIR`.
3. **Si es PDF o DOCX** (`_CONVERT_TO_TXT_EXTENSIONS`):
   - Se extrae su texto con `document_loader.load_document` (ver paso 5.a
     más abajo -- es la misma función que se usa luego para indexar).
   - El texto extraído se guarda como un `.txt` nuevo, con un nombre
     consecutivo si ya existe uno igual (`_next_available_txt_name`: `"Reporte.txt"`
     → `"Reporte (2).txt"`, etc. -- evita que un PDF y un DOCX con el mismo
     nombre base se pisen entre sí).
   - **El PDF/DOCX original se borra** -- en el servidor solo queda el `.txt`.
     Motivo medido en [notas-mejora-documentos.md](notas-mejora-documentos.md):
     re-parsear un PDF en cada reconstrucción del índice puede ser hasta ~14x
     más lento que leer un `.txt`, y un PDF corrupto puede tardar +60s.
   - Si la extracción falla (PDF corrupto, sin texto, etc.), se borra el
     archivo recién escrito y se responde error -- no queda nada a medias.
4. **TXT y XLSX no se convierten**, se quedan con su extensión original. El
   XLSX queda excluido a propósito porque el chunker lo indexa fila por
   fila (ver paso 5.b) -- convertirlo a texto plano perdería esa estructura.

## 4. Etiqueta de dependencia

`ingest_service.set_document_dependencia(nombre_final, dependencia_id)` guarda
(o actualiza) una fila en la tabla `document_dependencias` -- es la
referencia que luego usa el chatbot para decidir a qué dependencia
redirigir una pregunta escalada relacionada con ese documento.

## 5. Ingesta del archivo -- `ingest_service.ingest_single_file`

Primero llama a `vector_store.remove_document(nombre_final)` (por si ya
existían chunks de una versión anterior del mismo nombre), y luego procesa
el archivo (`_ingest_one`):

### 5.a Carga -- `app/rag/document_loader.py::load_document`

Lee el archivo **final** (el `.txt` convertido, o el TXT/XLSX original) y
lo divide en "páginas" de texto según el formato:

| Formato | Cómo se lee | "Páginas" resultantes |
|---|---|---|
| TXT | lectura directa (UTF-8, con reintento en Latin-1) | 1 |
| DOCX | `python-docx`, concatena todos los párrafos | 1 |
| PDF | `pypdf`, extrae texto de cada página | 1 por página del PDF |
| XLSX | `openpyxl`, cada fila se vuelve `"columna: valor \| columna: valor"` | 1 por hoja de cálculo |

(En la práctica, cuando el archivo llegó a este punto ya como `.txt`
convertido desde PDF/DOCX, se lee como TXT de una sola "página" -- la
paginación original del PDF ya se perdió al aplanarlo a texto plano.)

### 5.b División en fragmentos -- `app/rag/chunker.py::chunk_document`

Cada "página" se corta en fragmentos (chunks) según el tipo de documento:

- **Texto normal** (`_split_text`): fragmentos de ~`CHUNK_SIZE` caracteres
  con solapamiento (`CHUNK_OVERLAP`), cortando en el límite de oración o
  espacio más cercano para no partir palabras.
- **Hojas de cálculo** (`is_tabular=True`, `_pack_rows`): **cada fila es su
  propio fragmento** -- no se agrupan filas, para que una búsqueda por un
  horario o materia puntual no quede diluida entre otras filas.
- **Archivos de FAQ generadas** (`faq_generadas_*.txt`, `_pack_faq_entries`):
  cada bloque pregunta+respuesta (separado por línea en blanco) es su
  propio fragmento, por la misma razón.

Cada fragmento recibe un `chunk_id` estable (hash MD5 corto de
`nombre_archivo-página-índice`).

### 5.c Embeddings -- `app/rag/embeddings.py::embed_texts`

El texto de cada fragmento se pasa por el modelo local de Sentence
Transformers (`paraphrase-multilingual-MiniLM-L12-v2`, cargado una sola vez
como singleton) y se obtiene un vector normalizado por fragmento. Es
completamente local -- no llama a Groq ni a ninguna API externa.

### 5.d Guardado en el índice -- `app/rag/vector_store.py::add_chunks`

- Los vectores se agregan al índice FAISS en memoria (`IndexFlatIP` --
  producto interno sobre vectores normalizados = similitud coseno exacta).
- Los metadatos de cada fragmento (documento, página, texto,
  `dependencia_id`) se agregan en paralelo a `metadata.json` (FAISS solo
  guarda vectores, no metadatos).
- Se persisten ambos archivos a disco (`VECTOR_DB_DIR/index.faiss` y
  `VECTOR_DB_DIR/metadata.json`) -- de aquí en adelante el documento ya es
  parte del índice real, sin ningún paso adicional de "publicar" o
  "reconstruir".

## 6. Respuesta al administrador

`_upload_document` devuelve un `IngestResponse` (documentos procesados,
fragmentos creados, errores, y `final_filename` si el nombre cambió por la
conversión o por una colisión). Si `final_filename` es distinto del nombre
que el administrador subió, el frontend (`root.js`/`panel.js`) muestra una
alerta indicando con qué nombre quedó guardado.

## 7. Disponible de inmediato

No hace falta ningún paso extra: la siguiente pregunta que llegue al chat
(`/api/chat/stream` → `retrieve_context` → `vector_store.query`, ver
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md)) ya busca contra el índice
FAISS actualizado, así que el documento recién subido puede aparecer como
fuente desde la primera pregunta posterior a la subida.
