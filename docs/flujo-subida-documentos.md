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
- **Root** tiene además una segunda vía de entrada, exclusiva suya: el
  botón "+ Indexar sitio web" (mismo lugar que "+ Subir documento"), que no
  sube un archivo sino que dispara un rastreo automático de una URL y sus
  enlaces internos -- ver la sección 8 más abajo.

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
alerta indicando con qué nombre quedó guardado. Esta respuesta es
**síncrona** -- el navegador espera a que termine toda la ingesta. La vía
alterna de la sección 8 (rastrear un sitio web completo) puede tomar
minutos, así que en cambio responde de inmediato con un `job_id` y el
progreso se consulta aparte.

## 7. Disponible de inmediato

No hace falta ningún paso extra: la siguiente pregunta que llegue al chat
(`/api/chat/stream` → `retrieve_context` → `vector_store.query`, ver
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md)) ya busca contra el índice
FAISS actualizado, así que el documento recién subido puede aparecer como
fuente desde la primera pregunta posterior a la subida.

## 8. Vía alterna: rastreo automático de un sitio web

En vez de subir archivo por archivo, root puede pedirle al sistema que
recorra solo una URL y todas las que encuentre enlazadas dentro del mismo
dominio y ruta -- útil para poblar el índice con el contenido público de
la institución (ej. `unilibre.edu.co/cucuta`) sin descargar y subir cada
página a mano. Exclusivo de root (`POST /api/root/crawl-site`, protegido
con `require_root`) -- ni general ni dependencia lo ven en su panel.

### 8.a Qué pide el formulario

URL inicial (obligatoria), una ruta permitida opcional (si se deja vacía,
`web_crawler.default_path_prefix` la deriva de la propia ruta de la URL
inicial -- así un rastreo nunca se sale "sin querer" a todo el dominio),
profundidad máxima de enlaces (0-5), máximo de páginas (1-500) y una
dependencia opcional para etiquetar todo lo que se indexe.

### 8.b El rastreo en sí -- `app/rag/web_crawler.py::crawl_site`

Es un recorrido en anchura (BFS), página por página, con varias
protecciones:

- **Nunca sale del dominio+ruta permitida** (`is_allowed`) -- ni
  subdominios, ni redes sociales, ni portales externos que la página
  enlace, aunque el sitio real los tenga.
- **Respeta `robots.txt`** (`RobotsCache`, un `urllib.robotparser` por
  dominio) -- si el archivo no existe o no responde, asume que todo está
  permitido en vez de bloquear el rastreo entero por un detalle del
  servidor remoto.
- Un segundo de espera entre petición y petición
  (`REQUEST_DELAY_SECONDS`), para no saturar el servidor de la
  institución.
- El nombre de archivo de cada página sale de su propia URL
  (`url_to_filename`, un slug estable) -- la misma URL rastreada dos
  veces siempre produce el mismo nombre, así un segundo rastreo
  **sobreescribe** la versión anterior de esa página en vez de
  duplicarla.
- Cada página HTML se pasa por `trafilatura.extract`, que se queda solo
  con el contenido principal (descarta menús de navegación, pie de
  página, banners) -- validado manualmente contra el sitio real de la
  universidad antes de construir esta función.
- **Páginas de plantilla sin editar** (`is_placeholder_text`): un sitio
  real puede tener páginas publicadas por error o dejadas a medias, con
  texto de relleno ("Lorem ipsum dolor sit amet...") en vez de contenido
  real -- caso real encontrado rastreando el sitio de la universidad. Si
  ese relleno aparece casi al principio del texto extraído, la página
  **no se indexa** (sus enlaces sí se siguen igual, por si llevan a
  contenido real). El chequeo es por posición, no por sola presencia de
  la frase: una página real puede mencionar "Lorem ipsum" de pasada (ej.
  un blog cuya introducción es real pero que más abajo lista la vista
  previa de un post todavía sin redactar) -- esa sí se indexa igual, por
  el resto de su contenido legítimo.
- Si un enlace apunta a un PDF/DOCX/XLSX (`BINARY_EXTENSIONS`), se
  descarga su contenido crudo pero **no se indexa automáticamente** (ver
  8.d) -- requeriría el mismo tratamiento de conversión que ya tiene la
  subida manual (sección 3), y replicarlo aquí quedó fuera de alcance de
  la primera versión de esta función.

### 8.c Orquestación en segundo plano -- `app/services/crawl_job_service.py`

`start_crawl_job` lanza un hilo (`daemon=True`) y devuelve un `job_id` de
inmediato -- el navegador no espera a que termine. Ese hilo
(`_run_job`) recorre el generador de `crawl_site` y, por cada página de
texto:

1. Calcula el hash SHA-256 de su contenido y lo compara contra
   `ingest_service.get_document_hash_by_filename` (mismo mecanismo que
   `document_hashes` ya usa para detectar contenido duplicado en la
   subida manual). **Si es idéntico al de la última vez que se rastreó
   esa misma página, se salta por completo** -- no reescribe el archivo
   ni pasa por chunking/embeddings. Esto importa porque, a diferencia de
   subir un archivo (una acción puntual), un rastreo se puede repetir
   muchas veces sobre el mismo sitio, y la mayoría de páginas no cambian
   entre una corrida y la siguiente.
2. Si el contenido es nuevo o cambió, escribe el `.txt` en
   `DOCUMENTS_DIR`, marca el documento con
   `ingest_service.set_document_source_url` (la URL real, para que el
   estudiante pueda abrirla) y `set_document_downloadable(False)` (ver
   8.d), y llama a **la misma función de ingesta de la sección 5**
   (`ingest_service.ingest_single_file`) -- el rastreo no duplica el
   pipeline de chunking/embeddings/FAISS, lo reutiliza tal cual.
3. Una página que falla (error de red, contenido vacío, etc.) se cuenta
   como fallida y se sigue con la siguiente -- un solo error no aborta
   el resto del rastreo.

El progreso (`GET /api/root/crawl-site/{job_id}`) reporta, en vivo:
páginas indexadas, páginas sin cambios (saltadas), páginas fallidas, la
URL que se está procesando en ese momento, y la lista de errores. Root
puede cancelarlo entre una página y la siguiente
(`POST /api/root/crawl-site/{job_id}/cancel`). Este estado vive en
memoria, no en la base de datos -- si el servidor se reinicia a mitad de
un rastreo, las páginas ya indexadas quedan indexadas igual (se guardan
de a una, no todas al final), pero el progreso en sí se pierde y root
tendría que lanzarlo de nuevo.

### 8.d Documentos rastreados: no descargables, con enlace a la fuente real

Toda página indexada por un rastreo queda marcada `downloadable=False`
(columna `document_dependencias.downloadable`) -- no existe un archivo
"original" que ofrecer para descargar, solo la página web. En el chat del
estudiante, cuando una de estas páginas aparece como fuente, en vez de un
botón de descarga se muestra un enlace que abre la URL real
(`document_dependencias.source_url`) en una pestaña nueva.

Esta misma columna `downloadable` es independiente del rastreo -- ver
[casos-de-uso.md](casos-de-uso.md) para el caso de un admin marcando a
mano un documento subido normalmente como no descargable (ej. un PDF con
una imagen institucional desactualizada que igual se quiere seguir
usando como fuente de información).

### 8.e PDF/Word/Excel enlazados: pendientes de descarga manual

Cada archivo binario que el rastreo detecta (8.b) se guarda en la tabla
`crawl_pending_files` (`url`, `seed_url`, `dependencia_id`,
`created_at`) -- con `UNIQUE` en la URL, así que encontrarlo de nuevo en
un rastreo posterior no genera una segunda entrada. En el panel root
(pestaña Documentos) aparece una sección "Archivos pendientes de
descarga manual" con el enlace real (clicable, abre en pestaña nueva)
para que root lo descargue y lo suba a mano con "+ Subir documento" si
lo necesita, y un botón para descartarlo de la lista sin subir nada.
Esta lista **persiste en la base de datos** (no en el estado en memoria
del job de 8.c), así que sigue disponible aunque se cierre el modal de
progreso o se reinicie el servidor.
