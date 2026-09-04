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

## Propuesta: convertir PDF/DOCX a TXT automáticamente al subir

Idea planteada por el usuario: cuando se sube un documento que no es TXT,
extraer todo su texto y guardarlo como `.txt`, usando esa versión (no el
original) para el índice -- así toda reingesta futura es más rápida y no
quedan archivos pesados en `documents/`.

**Medición adicional** (mismo método, sobre los documentos de ejemplo
reales del proyecto):

| Formato | Tamaño | Promedio | vs. TXT |
|---|---|---|---|
| TXT (Reglamento) | 2.6 KB | 0.285 ms | referencia |
| XLSX (Horario) | 8.5 KB | 3.106 ms | ~11x |
| PDF (comparación, generado) | -- | 4.000 ms | ~14x |
| DOCX (Manual de Prácticas) | 36.4 KB | 12.623 ms | ~44x |

**Matices a resolver antes de implementar:**

1. **El costo hoy ya es "una sola vez por archivo"**, no por cada
   pregunta del chat -- desde la ingesta incremental, un documento solo se
   re-parsea al subirlo/recategorizarlo, o en una reconstrucción completa
   del índice. El beneficio real de convertir a TXT es sobre todo:
   reconstrucciones completas más rápidas, e inmunidad a que un PDF
   corrupto/pesado (como el caso real de +60s) se vuelva a parsear en cada
   reconstrucción futura.
2. **XLSX NO debería incluirse en esta conversión.** Hoy cada fila de un
   Excel se indexa como su propio fragmento (`chunker.py::_pack_rows`),
   una decisión atada a la extensión `.xlsx` -- convertirlo a `.txt` lo
   haría caer en el chunking por tamaño de caracteres (`_split_text`) y
   perdería la precisión de búsqueda por fila (horarios, tablas de datos).
   Además XLSX ya es rápido (3ms), así que no hay mucho que ganar ahí.
3. **Decisión pendiente sobre el archivo original**: ¿se descarta después
   de extraer el texto (como pidió el usuario, para no acumular archivos
   pesados), o se conserva aparte -sin usarlo para el índice- por si algún
   día hace falta el documento "oficial" con su formato/membrete original?
   Descartarlo es irreversible: ya no se podría re-extraer con un método
   mejor más adelante, ni ofrecer el archivo real para descarga.
4. Detalle de implementación a definir: cómo se muestra la fuente citada
   al estudiante si el archivo indexado es un `.txt` derivado de
   `Manual.docx` (¿se le sigue llamando "Manual.docx" en la cita, o pasa a
   llamarse "Manual.txt"?).

**Recomendación:** aplicar la conversión a PDF y DOCX únicamente (no
XLSX), decidiendo antes si el original se descarta o se conserva aparte.
