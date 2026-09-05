# Índice de documentación

El **[README.md](../README.md)** en la raíz del proyecto tiene la visión
general: qué es el proyecto, instalación paso a paso, arquitectura,
configuración y cómo ejecutar pruebas. Los documentos de esta carpeta
profundizan en partes específicas -- decisiones de diseño, flujos internos
detallados, y guías para usuarios concretos.

## Para usar el sistema

- **[manual-usuario.md](manual-usuario.md)** -- guía de uso para
  estudiantes (el chat), asesores (`/panel`) y administradores (`/root`):
  qué hace cada botón y cada pantalla.

## Para presentar/exponer el proyecto

- **[exposicion-guia.md](exposicion-guia.md)** -- guion y material de
  apoyo pensado para sustentar el proyecto (qué mostrar, en qué orden, y
  cómo explicar cada parte sin asumir conocimiento previo de RAG).

## Decisiones de diseño (el porqué de una elección concreta)

- **[decision-uso-de-groq.md](decision-uso-de-groq.md)** -- por qué Groq
  como proveedor del LLM y no otra alternativa.
- **[notas-mejora-documentos.md](notas-mejora-documentos.md)** -- por qué
  se convierten PDF/DOCX a `.txt` al subirlos (medido, no solo teoría).

## Arquitectura y estructura

- **[stack-tecnologico.md](stack-tecnologico.md)** -- de qué está hecho el
  proyecto (backend, RAG, frontend, testing, infraestructura, seguridad).
- **[estructura-del-proyecto.md](estructura-del-proyecto.md)** -- árbol de
  directorios completo y qué hace cada archivo.

## Flujos internos y conceptos (para quien va a tocar el código)

- **[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md)** -- qué pasa, paso a
  paso, desde que se envía una pregunta hasta que llega la respuesta
  (streaming, Groq, métricas).
- **[flujo-subida-documentos.md](flujo-subida-documentos.md)** -- qué
  pasa, paso a paso, desde que se sube un archivo hasta que queda
  indexado y buscable.
- **[conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md)** --
  glosario: qué es un chunk, qué es la ingesta, qué hace FAISS y cómo, y
  dónde vive cada cosa (SQLite vs. archivos del índice vectorial).
