# Notas para un futuro proceso de mejora de documentos

Este archivo reúne hallazgos y mediciones puntuales sobre el manejo de
documentos del proyecto, pensados como punto de partida cuando se aborde
un proceso más amplio de mejora de esa funcionalidad. No implica ningún
cambio de código por sí solo.

## TXT se procesa más rápido que PDF (medido, no solo teoría)

**Medición** (`app/rag/document_loader.load_document` +
`app/rag/chunker.chunk_document`, mismo contenido de texto exacto en ambos
formatos para aislar solo el costo de parsear cada uno, promedio de 200
repeticiones):

| Formato | Promedio | Mediana |
|---|---|---|
| TXT | 0.287 ms | 0.282 ms |
| PDF (simple, bien formado, 1 página) | 4.000 ms | 3.909 ms |

El PDF es **~14x más lento** que el TXT incluso en el mejor caso posible
(PDF simple y válido). La causa: `_load_txt` es una simple lectura de
archivo plano; `_load_pdf` usa `pypdf` para parsear la estructura binaria
del PDF (tabla de referencias cruzadas, objetos, streams de contenido) y
reconstruir el texto a partir de comandos de dibujo.

**Y ese es el mejor caso.** Ya se vivió el caso real en producción: un PDF
subido con la estructura interna dañada (muchas advertencias de `pypdf`
tipo "wrong pointing object") tardó **más de 60 segundos** en procesarse —
un PDF complejo o corrupto puede ser órdenes de magnitud más lento que el
caso simple medido arriba, mientras que un TXT prácticamente no tiene
forma de degradarse así.

### Implicaciones para un futuro proceso de mejora

- Si el mismo contenido puede entregarse como TXT en vez de PDF, siempre
  será más rápido de ingerir — insignificante para un documento suelto,
  pero se nota si se suben muchos documentos de una vez o PDFs grandes/complejos.
- Vale la pena considerar, más adelante: detectar PDFs "problemáticos" antes
  de procesarlos completos (advertencias de `pypdf` como señal), un límite
  de tiempo por documento durante la ingesta, o convertir/recomendar TXT
  para contenido que la propia institución redacta desde cero (reglamentos,
  FAQ) en vez de escanear/exportar a PDF innecesariamente.
- Ver también la sección "Consejo: datos puntuales que quedan enterrados"
  del [README.md](../README.md) — un problema relacionado (no de velocidad,
  sino de precisión de búsqueda) que también forma parte de la
  funcionalidad de documentos a revisar.
