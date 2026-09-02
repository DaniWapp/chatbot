"""Lógica de ingestión de documentos: carga -> chunking -> embeddings -> vector store.

Se usa tanto desde scripts/ingest.py (línea de comandos) como desde el
endpoint POST /api/ingest, para no duplicar el pipeline.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from app.config import settings
from app.rag import vector_store
from app.rag.chunker import chunk_document
from app.rag.document_loader import DocumentLoadError, load_document
from app.rag.embeddings import embed_texts


@dataclass
class IngestResult:
    documents_processed: int = 0
    documents_skipped: int = 0
    chunks_created: int = 0
    errors: List[str] = field(default_factory=list)


def _discover_documents() -> List[Path]:
    if not settings.DOCUMENTS_DIR.exists():
        return []
    return [
        p
        for p in sorted(settings.DOCUMENTS_DIR.iterdir())
        if p.is_file()
        and p.suffix.lower() in settings.ALLOWED_EXTENSIONS
        # Ignora archivos temporales de bloqueo que Word/Excel crean mientras
        # el documento original está abierto (ej. "~$Horario.xlsx").
        and not p.name.startswith("~$")
    ]


def run_ingestion(rebuild: bool = True, log=print) -> IngestResult:
    """Procesa todos los documentos en DOCUMENTS_DIR y reconstruye el índice vectorial.

    rebuild=True: borra la colección existente y la reconstruye desde cero
    (simple y predecible para un proyecto académico; evita índices duplicados
    o desactualizados). rebuild=False solo agrega documentos sin borrar.
    """
    result = IngestResult()
    files = _discover_documents()

    if not files:
        log(f"No se encontraron documentos válidos en {settings.DOCUMENTS_DIR}")
        result.errors.append(f"No hay documentos en {settings.DOCUMENTS_DIR}")
        return result

    if rebuild:
        log("Reconstruyendo índice vectorial desde cero...")
        vector_store.reset_collection()

    for path in files:
        try:
            log(f"Procesando: {path.name}")
            document = load_document(path)
            chunks = chunk_document(document, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
            if not chunks:
                raise DocumentLoadError("No se generaron fragmentos de texto.")

            embeddings = embed_texts([c.text for c in chunks])
            vector_store.add_chunks(chunks, embeddings)

            result.documents_processed += 1
            result.chunks_created += len(chunks)
            log(f"  -> {len(chunks)} fragmentos indexados")
        except DocumentLoadError as exc:
            result.documents_skipped += 1
            msg = f"{path.name}: {exc}"
            result.errors.append(msg)
            log(f"  [OMITIDO] {msg}")
        except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo y seguir
            result.documents_skipped += 1
            msg = f"{path.name}: error inesperado ({exc})"
            result.errors.append(msg)
            log(f"  [OMITIDO] {msg}")

    log(
        f"Ingestión completa: {result.documents_processed} documentos, "
        f"{result.chunks_created} fragmentos, {result.documents_skipped} omitidos."
    )
    return result
