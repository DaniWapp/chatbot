# Por qué se eligió `paraphrase-multilingual-MiniLM-L12-v2` para los embeddings

Este documento explica la decisión detrás del modelo de embeddings que usa
el chatbot para la búsqueda semántica, en vez de otras alternativas. El
razonamiento resumido también vive en el [README.md](../README.md)
(sección de tecnologías) y en
[stack-tecnologico.md](stack-tecnologico.md); este archivo lo desarrolla
con más detalle, igual que [decision-uso-de-groq.md](decision-uso-de-groq.md)
hace para el LLM. Para **cómo funciona** el modelo por dentro
(tokenización, pooling, normalización, por qué produce vectores de 384
números), ver [conceptos-embeddings.md](conceptos-embeddings.md) -- este
documento es sobre el **porqué de elegirlo**, no sobre su mecánica.

## 1. Qué es este modelo, concretamente

`paraphrase-multilingual-MiniLM-L12-v2` es un modelo publicado por el
proyecto `sentence-transformers`, distilado desde XLM-RoBERTa y afinado
específicamente para la tarea de *paraphrase identification*
(reconocer cuándo dos frases dicen lo mismo, incluso en idiomas
distintos) -- exactamente la tarea que necesita este chatbot: encontrar
el chunk que responde una pregunta, no el que comparte más palabras
literales con ella. Se descarga una sola vez desde Hugging Face
(~470MB) y se cachea en disco (ver `app/rag/embeddings.py`).

## 2. Por qué este modelo y no otras alternativas

| Alternativa | Por qué no se usó (en el contexto de este proyecto) |
|---|---|
| **API de embeddings en la nube** (OpenAI `text-embedding-3-small`, Cohere, Gemini, etc.) | Cada chunk ingestado y cada pregunta requeriría una llamada de red a un tercero, con costo por uso y una nueva dependencia externa -- justo lo que ya se evitó con Groq para la generación (ver [decision-uso-de-groq.md](decision-uso-de-groq.md)). Aquí no hay ninguna razón para pagar por algo que corre perfectamente bien local y gratis. |
| **Modelo de embeddings en inglés** (p. ej. `all-MiniLM-L6-v2`, el más popular de `sentence-transformers`) | Es el más liviano y rápido de su familia, pero está entrenado casi exclusivamente en inglés -- con documentos y preguntas 100% en español, perdería calidad semántica justo donde más importa. |
| **Modelo multilingüe más grande** (p. ej. `paraphrase-multilingual-mpnet-base-v2`, 768 dimensiones) | Puede capturar algo más de matiz semántico, pero pesa el doble por vector (768 vs 384) y es más lento de generar e indexar -- un costo real en un VPS sin GPU, sin una ganancia de calidad que se note en la práctica para preguntas institucionales relativamente directas. |
| **Modelo local pero no multilingüe-específico** (un BERT/RoBERTa en español entrenado para otra tarea, p. ej. clasificación) | No está afinado para medir *similitud semántica* entre frases -- es la tarea concreta que resuelve `paraphrase-multilingual-MiniLM-L12-v2` y no algo que cualquier modelo de lenguaje en español resuelva bien "gratis". |

En resumen, la combinación que pesó más fue: **gratis y local** (sin
llamada de red ni costo por búsqueda), **entrenado para similitud
semántica** (no un modelo genérico reutilizado a la fuerza), **bueno en
español** (multilingüe de verdad, no solo "no falla" en otros idiomas), y
**liviano** (384 dimensiones, corre rápido sin GPU) -- ver
[conceptos-embeddings.md](conceptos-embeddings.md#por-qué-384-números-y-no-otro-tamaño)
para el desglose real de esa última parte (arquitectura MiniLM-L12-H384,
mitad del ancho de BERT-base).

## 3. Riesgos y limitaciones a tener en cuenta

- **Techo de calidad**: al ser un modelo compacto (384 dimensiones, 12
  capas), no captura matices semánticos tan finos como un modelo mucho
  más grande. Para preguntas institucionales relativamente directas esto
  no se ha notado como un problema; para textos muy ambiguos o técnicos
  podría perderse algo de precisión.
- **Descarga inicial**: la primera vez que corre el servidor, descarga
  ~470MB desde Hugging Face -- si esa descarga falla (sin internet en el
  primer arranque, por ejemplo), la ingesta y la búsqueda no funcionan
  hasta que se complete.
- **Cambiar de modelo no es gratis**: si en el futuro se cambiara
  `EMBEDDING_MODEL` por otro (incluso a una versión distinta del mismo
  modelo), los vectores ya guardados en `vector_db/index.faiss` dejarían
  de ser comparables con los nuevos -- haría falta reingestar **todo** el
  corpus desde cero (`run_ingestion(rebuild=True)`), no solo los
  documentos nuevos.
- **Sin aceleración por GPU**: corre sobre CPU en el VPS. Es aceptable
  para el volumen de una facultad (miles de chunks, no millones), pero no
  escalaría igual de bien a un corpus mucho más grande sin GPU.
