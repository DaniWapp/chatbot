# Conceptos: chunk, ingesta, FAISS y dónde vive cada cosa

Glosario de referencia para los términos usados en
[flujo-subida-documentos.md](flujo-subida-documentos.md) y
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md). No implica ningún cambio de
código.

## ¿Qué es un chunk (fragmento)?

Un pedazo pequeño de texto en el que se divide un documento antes de
indexarlo. En vez de guardar "el PDF completo" como un solo bloque, se
corta en piezas de ~500 caracteres (o una fila de Excel, o una pregunta+
respuesta de FAQ, según el tipo de archivo -- ver `app/rag/chunker.py`).

¿Por qué dividir en vez de guardar el documento entero?

1. **Búsqueda precisa**: cuando alguien pregunta algo, el sistema busca
   cuáles fragmentos son más parecidos a la pregunta por similitud
   semántica. Si el "fragmento" fuera el documento completo, no se podría
   distinguir qué parte específica es relevante.
2. **Límite de contexto**: no se le puede pasar un documento de 50 páginas
   completo al LLM en cada pregunta -- se le pasan solo los 3-4 fragmentos
   más relevantes encontrados.

En código, cada chunk es un objeto `Chunk` (`app/rag/chunker.py`) con
`chunk_id`, `document` (de qué archivo salió), `page` y `text`.

## ¿Qué es la ingesta?

El proceso completo de convertir un archivo recién subido en algo que el
chatbot puede buscar: leer el archivo → cortarlo en chunks → convertir
cada chunk en un vector numérico (embedding) → guardar esos vectores en el
índice de búsqueda. "Ingestar un documento" = "meterlo al catálogo de
búsqueda del chatbot". Antes de la ingesta, el archivo es solo un archivo
en una carpeta; después, sus fragmentos son buscables y pueden aparecer
como contexto en una respuesta. Ver el detalle paso a paso en
[flujo-subida-documentos.md](flujo-subida-documentos.md).

## ¿Qué hace FAISS y cómo?

FAISS (Facebook AI Similarity Search) es una librería para buscar, entre
muchísimos vectores numéricos, cuáles son los más "parecidos" a un vector
de consulta, y hacerlo rápido. Es el motor de búsqueda semántica del
proyecto: no busca por palabras exactas, busca por significado.

**Qué hace aquí, concretamente:** cada chunk se convierte en un vector
(~384 números, el embedding -- ver `app/rag/embeddings.py`). FAISS guarda
todos esos vectores en un índice. Cuando llega una pregunta, esta también
se convierte en un vector con el mismo modelo, y FAISS responde: "de todos
los vectores guardados, estos son los `top_k` más parecidos a este, y así
de parecidos son".

**Cómo mide "parecido":** el proyecto usa `IndexFlatIP`
(`app/rag/vector_store.py`):

- **IP** = "Inner Product" (producto punto entre dos vectores). Como los
  embeddings se generan normalizados (`normalize_embeddings=True` en
  `embeddings.py`), el producto punto entre dos vectores normalizados
  **es matemáticamente igual a la similitud coseno** -- un truco estándar
  para no necesitar un índice especial de coseno. El resultado es un
  número entre -1 y 1: cerca de 1 = significan casi lo mismo, cerca de 0 =
  sin relación.
- **Flat** = búsqueda exacta por fuerza bruta: compara el vector de la
  pregunta contra **todos** los vectores guardados, uno por uno, sin
  aproximar. Existen índices más rápidos (aproximados) para millones de
  vectores, pero con el corpus de una facultad (unos pocos miles de
  fragmentos) la búsqueda exacta ya es rapidísima -- por eso se mide
  ~15-25ms de `retrieval_ms` en pruebas reales.

**Cómo se relaciona el vector con el texto real:** FAISS solo guarda
números, no sabe qué documento o texto representa cada vector. Por eso se
mantiene un `metadata.json` en paralelo, en el mismo orden en que se
fueron agregando los vectores: si FAISS dice "el vector en la posición 47
tiene similitud 0.82", el código busca `metadata[47]` y ahí está el
documento, la página y el texto real de ese fragmento.

**Persistencia:** `faiss.write_index()`/`read_index()` guardan y cargan el
índice completo como un archivo binario, para que sobreviva a un reinicio
del servidor sin reprocesar todos los documentos.

## ¿Dónde se guardan los chunks?

En dos archivos separados, dentro de `vector_db/` (raíz del proyecto,
configurable con la variable de entorno `VECTOR_DB_DIR`):

| Archivo | Qué guarda | Formato |
|---|---|---|
| `vector_db/index.faiss` | El **vector** (embedding) de cada chunk | Binario, propio de FAISS |
| `vector_db/metadata.json` | El **texto real** de cada chunk, más `document`, `page`, `chunk_id` y `dependencia_id` | JSON, lista en el mismo orden que los vectores |

## ¿Y qué se guarda en SQLite (`history.db`)?

Solo **una pieza pequeña**, no los chunks ni sus vectores: la tabla
`document_dependencias`.

```sql
CREATE TABLE document_dependencias (
    filename TEXT PRIMARY KEY,
    dependencia_id INTEGER,
    updated_at TEXT NOT NULL
)
```

Una fila por documento: el nombre del archivo y a qué dependencia está
etiquetado (o `NULL` si es general/compartido). La escribe
`ingest_service.set_document_dependencia()`. Es puramente una etiqueta de
"pertenencia" -- el chatbot la usa para decidir a qué dependencia
redirigir una pregunta escalada relacionada con ese documento.

**Lo que NO va a SQLite:**
- El texto de los chunks → `vector_db/metadata.json`.
- Los embeddings/vectores → `vector_db/index.faiss`.
- El archivo original o convertido (`.txt`/`.pdf`/`.docx`/`.xlsx`) →
  carpeta `documents/` en disco, no en ninguna base de datos.

Son dos almacenamientos separados que no dependen uno del otro para
funcionar, pero se combinan: `dependencia_id` se guarda tanto en
`document_dependencias` (SQLite) como copiado en cada entrada de
`metadata.json` (vector_db) -- por eso al recategorizar un documento hay
que reingestarlo, para que la copia que vive en `metadata.json` también se
actualice.
