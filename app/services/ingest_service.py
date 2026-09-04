"""Lógica de ingestión de documentos: carga -> chunking -> embeddings -> vector store.

Se usa tanto desde scripts/ingest.py (línea de comandos) como desde el
endpoint POST /api/ingest, para no duplicar el pipeline.
"""
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.rag import vector_store
from app.rag.chunker import chunk_document
from app.rag.document_loader import DocumentLoadError, load_document
from app.rag.embeddings import embed_texts
from app.services import history


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class IngestResult:
    documents_processed: int = 0
    documents_skipped: int = 0
    chunks_created: int = 0
    errors: List[str] = field(default_factory=list)


def discover_documents() -> List[Path]:
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


def get_document_dependencia(filename: str) -> Optional[int]:
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            "SELECT dependencia_id FROM document_dependencias WHERE filename = ?", (filename,)
        ).fetchone()
    return row[0] if row else None


def set_document_dependencia(filename: str, dependencia_id: Optional[int]) -> None:
    """NULL en dependencia_id marca el documento como general/compartido
    (no perteneciente a ninguna dependencia en particular)."""
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            """
            INSERT INTO document_dependencias (filename, dependencia_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                dependencia_id = excluded.dependencia_id,
                updated_at = excluded.updated_at
            """,
            (filename, dependencia_id, _now()),
        )
        conn.commit()


def delete_document_dependencia(filename: str) -> None:
    with history.db_lock():
        conn = history.get_connection()
        conn.execute("DELETE FROM document_dependencias WHERE filename = ?", (filename,))
        conn.commit()


def _ingest_one(path: Path, dependencia_id: Optional[int], result: IngestResult, log) -> None:
    """Procesa un solo archivo (carga -> chunking -> embeddings) y agrega
    sus chunks al índice. Actualiza result in-place; nunca lanza (los
    fallos quedan registrados en result.errors), para que el llamador
    pueda seguir con el resto del lote si viene de run_ingestion."""
    try:
        log(f"Procesando: {path.name}")
        document = load_document(path)
        chunks = chunk_document(document, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        if not chunks:
            raise DocumentLoadError("No se generaron fragmentos de texto.")

        embeddings = embed_texts([c.text for c in chunks])
        vector_store.add_chunks(chunks, embeddings, dependencia_id=dependencia_id)

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


def run_ingestion(rebuild: bool = True, log=print) -> IngestResult:
    """Procesa todos los documentos en DOCUMENTS_DIR y reconstruye el índice vectorial.

    rebuild=True: borra la colección existente y la reconstruye desde cero
    (simple y predecible; recalcula los embeddings de TODO el corpus, así
    que para tocar un solo archivo conviene ingest_single_file en vez de
    esto). rebuild=False solo agrega documentos sin borrar.
    """
    result = IngestResult()
    files = discover_documents()

    if not files:
        log(f"No se encontraron documentos válidos en {settings.DOCUMENTS_DIR}")
        result.errors.append(f"No hay documentos en {settings.DOCUMENTS_DIR}")
        return result

    if rebuild:
        log("Reconstruyendo índice vectorial desde cero...")
        vector_store.reset_collection()

    for path in files:
        _ingest_one(path, get_document_dependencia(path.name), result, log)

    log(
        f"Ingestión completa: {result.documents_processed} documentos, "
        f"{result.chunks_created} fragmentos, {result.documents_skipped} omitidos."
    )
    return result


def ingest_single_file(path: Path, dependencia_id: Optional[int] = None, log=print) -> IngestResult:
    """Ingesta (o reingesta) UN SOLO archivo sin tocar el resto del índice
    -- mucho más barato que run_ingestion(rebuild=True) cuando lo único que
    cambió es ese archivo (subida nueva, recategorización, o una FAQ
    aceptada): no vuelve a calcular embeddings de los demás documentos.

    Primero quita del índice cualquier chunk que ese archivo ya tuviera
    (vector_store.remove_document), por si se le agregó contenido a una
    versión anterior (por ejemplo, otra FAQ más en el mismo archivo de
    preguntas frecuentes de una dependencia) -- así no queda duplicado."""
    result = IngestResult()
    vector_store.remove_document(path.name)
    _ingest_one(path, dependencia_id, result, log)
    return result
