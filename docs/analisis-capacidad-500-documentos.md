# Análisis de capacidad: ¿sigue siendo viable con 500 documentos indexados?

Este documento responde una pregunta concreta: si la institución llega a
tener 500 documentos indexados (en vez de los que había al momento de
medir), ¿el sistema sigue respondiendo rápido, y la memoria RAM alcanza?
Ya no es un escenario puramente hipotético -- con la indexación
automática de sitios web (ver
[flujo-subida-documentos.md](flujo-subida-documentos.md)), un solo
rastreo puede indexar hasta 500 páginas de golpe, así que llegar a ese
volumen es un camino real, no solo teórico. Es un análisis técnico
basado en mediciones reales del sistema en producción, no en
estimaciones teóricas -- cada número está marcado como **medido** o
**extrapolado** a partir de una medición real.

**Conclusión corta: sí, sigue siendo viable, en un servidor con los
recursos ya recomendados en
[instalacion-linux.md](instalacion-linux.md)** (2 vCPU / 4 GB RAM). El
crecimiento del índice a 500 documentos es de apenas unas decenas de
megabytes -- un margen de error frente a lo que ya consume el sistema
hoy con 17 documentos. La razón de fondo, explicada abajo, es que el
costo real dominante de cada pregunta (el re-ranking) **no depende del
tamaño del corpus**.

## Supuesto de partida: "archivo de tamaño mediano"

Se define como **~20 KB de texto extraído** (unas 8-10 páginas de un
reglamento o guía institucional) -- calibrado contra el documento real
más grande del corpus actual: el Reglamento Estudiantil real (83.141
bytes → 92 fragmentos reales, medido en producción) da una razón de
**~904 bytes por fragmento** para texto corrido (`CHUNK_SIZE=1000`
caracteres, con solapamiento). A 20 KB por archivo, eso da **~22
fragmentos por archivo**.

## Datos base medidos en producción el 2026-09-10 (17 archivos, 619 fragmentos)

Punto en el tiempo, no una cifra que se mantenga fija -- el corpus real
cambia con cada documento que se sube, se elimina o se rastrea. Sirve
como línea base real para la extrapolación de abajo, no como el conteo
actual del sistema.

| Métrica | Valor medido |
|---|---|
| `vector_db/index.faiss` | 1.89 MB (3.060 bytes/fragmento) |
| `vector_db/metadata.json` | 549 KB (887 bytes/fragmento) |
| Memoria del proceso (modelo de embeddings + re-ranker ya cargados) | ~1.2 GB, **fija**, no depende del tamaño del corpus |
| Ingesta completa desde cero (17 archivos, 619 fragmentos) | 41.7 s reales (incluye la carga del modelo) |
| Construcción del índice BM25 completo (516 fragmentos, medido en una sesión anterior) | 24.89 ms |
| Búsqueda FAISS por pregunta (516 fragmentos, medido en una sesión anterior) | 1.13 ms |
| Re-ranking por pregunta (el costo real dominante) | 500 ms – 7.5 s, según la carga de CPU disponible en ese momento |

## Qué escala con el tamaño del corpus, y qué no

Esta es la parte que explica por qué el sistema sigue siendo viable a
500 documentos:

- **Escala con el corpus** (linealmente, pero desde una base muy
  pequeña): el tamaño en disco/RAM de `index.faiss` y `metadata.json`,
  la búsqueda FAISS por pregunta, y la reconstrucción del índice léxico
  BM25 (que ocurre una vez por cada documento que se sube o modifica,
  ver `app/rag/vector_store.py::_rebuild_bm25_index`). Un rastreo de
  sitio web grande concentra ese costo: puede disparar la reconstrucción
  cientos de veces seguidas en minutos (una vez por página nueva o
  cambiada) en vez de una vez cada tanto como con subidas manuales. Esto
  se mitiga en parte con el mismo mecanismo del punto siguiente: una
  página que no cambió desde el último rastreo (comparada por hash
  SHA-256 contra `document_hashes`) se salta por completo, sin pagar
  ningún costo de reingesta.
- **NO escala con el corpus** (se mantiene constante): el re-ranking --
  el paso que de verdad domina el tiempo de respuesta de cada pregunta
  -- porque siempre trabaja sobre una cantidad fija de candidatos
  (`RERANK_CANDIDATE_K` + `LEXICAL_CANDIDATE_K` = 30 como máximo,
  configurado en `app/config.py`), sin importar si hay 17 o 5.000
  documentos indexados. Una pregunta a los 500 documentos tarda,
  aproximadamente, lo mismo que hoy con 17.
- Tampoco escala la memoria fija del proceso (~1.2 GB): es el modelo de
  embeddings y el modelo de re-ranking cargados una sola vez en RAM al
  arrancar, independiente de cuántos documentos haya.

## Tabla comparativa: 100 / 300 / 500 archivos medianos

| | **100 archivos** | **300 archivos** | **500 archivos** |
|---|---|---|---|
| Fragmentos estimados (~22/archivo) | ~2.200 | ~6.600 | ~11.000 |
| `index.faiss` (extrapolado, 3.060 B/frag) | ~6.7 MB | ~20.2 MB | ~33.7 MB |
| `metadata.json` (extrapolado, ~1.1 KB/frag)* | ~2.4 MB | ~7.3 MB | ~12.1 MB |
| **Total `vector_db/` en disco y en RAM** | **~9 MB** | **~27.5 MB** | **~46 MB** |
| Memoria total del proceso (1.2 GB base + índice) | ~1.21 GB | ~1.23 GB | ~1.25 GB |
| Búsqueda FAISS por pregunta (extrapolado, lineal) | ~4 ms | ~12 ms | ~24 ms |
| Reconstrucción BM25 por cada documento subido (extrapolado, lineal) | ~106 ms | ~318 ms | ~530 ms |
| **Re-ranking por pregunta (el costo real)** | **500 ms – 7.5 s** | **500 ms – 7.5 s** | **500 ms – 7.5 s** |
| Ingesta completa desde cero (extrapolado) | ~2.5 min | ~7.4 min | ~12.3 min |
| Riesgo de confusión semántica entre documentos parecidos | Bajo | Medio | Medio-alto |

\* `metadata.json` se proyecta a ~1.1 KB/fragmento en vez de los 887 B
medidos hoy, porque el corpus actual mezcla muchos fragmentos cortos
(FAQ, filas de horario); un corpus de archivos medianos con texto
corrido tiende a fragmentos más cercanos al tamaño completo configurado
(`CHUNK_SIZE=1000`).

## El único riesgo real no es de rendimiento, es de precisión

Lo que sí empeora con más documentos no es velocidad ni memoria, es la
probabilidad de que dos fragmentos de documentos distintos compartan
estructura de frase por casualidad (ej. dos FAQ con la forma "¿Cuál es
el precio de X para el año Y?", una de un programa y otra de otro) y el
modelo de embeddings los confunda. Esto ya ocurrió en producción real
con el corpus actual (mucho antes de llegar a 500 documentos) y quedó
mitigado con dos capas ya implementadas:

1. **Filtrado por fuentes realmente usadas** (`llm.py::extract_used_sources`)
   -- el LLM declara qué documentos usó de verdad, y solo esos se
   muestran como fuente.
2. **Reglas de coincidencia de aspecto y entidad en el prompt** (reglas
   2b y 2c de `_build_system_prompt`) -- el LLM debe verificar que el
   CONTEXTO sea sobre el mismo tema y el mismo programa/entidad
   específico que se pregunta, no uno distinto con redacción parecida.

Estas mitigaciones son las que hacen que el crecimiento del corpus siga
siendo manejable a 500 documentos, en vez de degradar la calidad de las
respuestas a medida que crece.

## Conclusión

Con los recursos mínimos ya recomendados para instalar el sistema (2
vCPU / 4 GB RAM, ver [instalacion-linux.md](instalacion-linux.md)), 500
documentos de tamaño mediano son perfectamente viables: el crecimiento
de memoria es de apenas ~46 MB, el tiempo de respuesta por pregunta no
cambia (está limitado por configuración, no por el tamaño del corpus), y
el único riesgo real -- precisión ante documentos con redacción
parecida -- ya tiene mitigaciones activas en el sistema.
