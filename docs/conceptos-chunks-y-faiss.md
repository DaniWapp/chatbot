# Conceptos: chunk, ingesta, FAISS y dónde vive cada cosa

Glosario de referencia para los términos usados en
[flujo-subida-documentos.md](flujo-subida-documentos.md) y
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md). No implica ningún cambio de
código.

## ¿Qué es un chunk (fragmento)?

Un pedazo pequeño de texto en el que se divide un documento antes de
indexarlo. En vez de guardar "el PDF completo" como un solo bloque, se
corta en piezas de `CHUNK_SIZE` caracteres (1000 por defecto -- ver
`app/config.py`), con `CHUNK_OVERLAP` caracteres (150 por defecto) de
traslape entre un chunk y el siguiente, para que una idea que caiga justo
en el corte no se pierda por completo en ninguno de los dos. Excepciones
por tipo de archivo: una fila de Excel, o una pregunta+respuesta de FAQ,
van completas en su propio chunk sin partirse (ver `app/rag/chunker.py`).

El traslape real casi nunca es exactamente 150 caracteres: el algoritmo
(`_split_text` en `app/rag/chunker.py`) busca el punto o el espacio más
cercano dentro de esa ventana para no cortar una oración a la mitad. Por
ejemplo, sobre un párrafo real de 1389 caracteres, el resultado fue:

```
chunk 0: caracteres [0, 878)
chunk 1: caracteres [850, 1389)   <- solo 28 caracteres de traslape real
```

El chunk 1 empieza repitiendo la última frase del chunk 0 para que esa
idea no quede huérfana en ninguno de los dos fragmentos.

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
(384 números, el embedding -- ver `app/rag/embeddings.py`). Cómo se genera
ese vector exactamente (tokenización, contextualización, pooling,
normalización) está fuera del alcance de este documento -- ver
[conceptos-embeddings.md](conceptos-embeddings.md). FAISS guarda
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

## ¿Cómo se usan los chunks al responder una pregunta?

FAISS por sí solo no decide la respuesta final -- solo entrega candidatos.
El camino completo, desde que llega la pregunta:

1. La pregunta se convierte en un vector con el mismo modelo de embeddings
   usado en la ingesta (tienen que caer en el mismo "espacio de
   significado" para poder compararse).
2. FAISS compara ese vector contra todos los guardados y devuelve los
   `RERANK_CANDIDATE_K` (20 por defecto) más parecidos por embeddings,
   cada uno con su similitud.
3. **En paralelo, una búsqueda léxica (BM25)** compara las palabras
   literales de la pregunta contra las de cada fragmento y devuelve hasta
   `LEXICAL_CANDIDATE_K` (10 por defecto) candidatos adicionales --
   ninguno de los dos conjuntos se descarta por similitud/puntaje todavía,
   solo se unen sin duplicar por `chunk_id`. Hace falta porque el modelo
   de embeddings a veces confunde dos temas cortos y parecidos (caso real
   documentado en
   [busqueda-lexica-bm25.md](busqueda-lexica-bm25.md): "Cálculo
   Diferencial" perdiendo contra "Álgebra Lineal" en la similitud de
   embeddings) -- BM25 encuentra por coincidencia exacta de palabras lo
   que al embedding se le escapa por significado.
4. Un modelo de re-ranking (cross-encoder) reordena **todos** los
   candidatos combinados comparando la pregunta y cada fragmento
   **juntos** (no por separado, como hace el embedding) para juzgar
   relevancia real, y descarta los que no superen `RERANK_MIN_SCORE`
   (0.05 por defecto) -- corre local, sin costo de Groq. Ver
   `app/rag/retriever.py`. Este paso, no `SIMILARITY_THRESHOLD`, es el
   filtro de relevancia real cuando el re-ranking está activo (el caso
   normal) -- ver más abajo.
5. Se conservan los `TOP_K` (4 por defecto) mejores fragmentos que
   sobrevivieron, y esos son los que se envían como contexto al LLM junto
   con la pregunta -- puede haber menos de `TOP_K` si menos fragmentos
   fueron realmente relevantes; nunca se rellena con fragmentos débiles
   solo para completar el cupo.

Este es también el punto donde actúa `drop_superseded_by_vigencia` (ver
`app/rag/retriever.py`): antes del paso 5, si dos documentos candidatos
tienen alta similitud entre sí y ambos tienen `vigente_desde` asignado, se
descarta el más antiguo -- salvo que la pregunta mencione explícitamente
un año que corresponda al documento antiguo.

### ¿Cómo calcula el cross-encoder ese puntaje de relevancia?

A diferencia de los embeddings (que codifican la pregunta y el fragmento
**por separado**, en dos pasadas independientes, y los comparan después
con un producto punto -- ver
[conceptos-embeddings.md](conceptos-embeddings.md)), el cross-encoder los
concatena en **una sola secuencia** desde el principio (verificado contra
el modelo real, `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`):

```
<s> ▁requisitos ▁de ▁grado </s></s> ▁Arti culo ▁22. ▁Es ▁requisit o ... </s>
```

`</s></s>` (doble marcador de fin) es el separador entre pregunta y
fragmento en este tokenizador -- no hay un id de "segmento A/B" aparte,
como sí tiene BERT clásico. Esa secuencia pasa junta por las mismas 12
capas de atención que usan los embeddings (arquitectura MiniLM-L12-H384),
así que cada palabra de la pregunta puede "ver" directamente cada palabra
del fragmento -- algo que dos vectores calculados por separado no pueden
hacer.

La salida de esas 12 capas sigue siendo caja negra, pero la
**cabeza de clasificación** final sí es inspeccionable
(`XLMRobertaClassificationHead`, confirmado con `model.classifier` en el
modelo real cargado):

1. **`dense`**: capa 384→384 con activación `tanh`, aplicada al vector
   final del token `<s>`.
2. **`out_proj`**: capa 384→1 -- multiplica esos 384 valores por 384
   pesos aprendidos y sesga (`bias`) la suma. Es el mismo tipo de
   operación que el producto punto de embeddings (multiplicar y sumar),
   solo que aquí los "pesos" no son otro vector de significado, sino
   coeficientes aprendidos específicamente para juzgar relevancia
   pregunta-fragmento.

Verificado con los pesos reales para un par pregunta-fragmento real
(pregunta "requisitos de grado" contra un fragmento de
`Calendario_Academico_EJEMPLO.txt`): recalculando a mano la suma de los
384 productos más el bias da **-2.6905599...**, contra
**-2.6905601...** que devuelve el modelo completo -- la diferencia es
solo redondeo de punto flotante. Ese logit crudo (sin acotar, por eso
puede ser negativo) es el que después pasa por sigmoide para compararse
con `RERANK_MIN_SCORE`.

### ¿Por qué esos valores de umbral, y no otros?

`RERANK_MIN_SCORE = 0.05` está documentado y calibrado desde el commit
`c0aba63`: el cross-encoder devuelve logits crudos (pueden ser negativos),
no probabilidades -- comparar 0.3 directamente contra eso rechazaba
incluso fragmentos correctos. Tras aplicar sigmoide, datos reales de
`evaluation/evaluate.py` mostraron un fragmento correcto con confianza
0.127 y uno incorrecto con 0.002 -- 0.05 queda cómodo entre ambos.

`SIMILARITY_THRESHOLD = 0.35` viene desde el primer commit del proyecto,
sin ese mismo respaldo documentado -- así que se calibró después, con el
mismo método, corriendo `evaluation/test_questions.json` (10 preguntas
reales) contra el índice real. **Importante:** desde que se agregó la
búsqueda léxica, este umbral solo se usa si `RERANK_ENABLED=False` (sin
re-ranking, no hay un juez más preciso disponible). Con re-ranking
activo -- el caso normal -- ya no se aplica antes de re-rankear: el
filtro real pasó a ser `RERANK_MIN_SCORE`, precisamente porque un
fragmento correcto puede tener una similitud de embeddings baja (ver
[busqueda-lexica-bm25.md](busqueda-lexica-bm25.md)) y aun así ser
exactamente lo que se necesita. La calibración de abajo sigue siendo
válida como referencia de qué tan bien separa la similitud de embeddings
lo relevante de lo irrelevante en este corpus, solo que ya no es la
decisión final:

- Las 7 preguntas con respuesta correcta obtuvieron similitud entre
  **0.42 y 0.73** -- todas sobre 0.35, con margen real.
- 2 de las 3 preguntas genuinamente sin información cayeron en **0.16 y
  0.31** -- por debajo de 0.35, correctamente rechazadas.
- La tercera ("calendario académico del año 2030") obtuvo **0.79** --
  más alto que varias respuestas correctas, porque habla del mismo tema
  indexado (calendario académico), solo que de otro año. La similitud de
  embeddings mide de qué *trata* el texto, no si el año coincide -- ningún
  umbral puede resolver ese caso por sí solo. Por eso existe una regla
  aparte en el prompt del sistema (no asumir que el CONTEXTO aplica a un
  año distinto al que la pregunta pide explícitamente), no el umbral.

La documentación oficial de Sentence-Transformers
([sbert.net](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html))
no recomienda ningún valor universal de corte -- deja la calibración al
caso de uso, que es exactamente lo que se hizo aquí.

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
