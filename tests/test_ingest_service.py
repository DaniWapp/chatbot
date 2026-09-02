"""Pruebas del proceso de ingestión (carga -> chunking -> embeddings -> vector store).

Se simulan los embeddings y el vector store para que el test corra rápido y
sin depender de descargar el modelo real de Sentence Transformers.
"""
from unittest.mock import patch

from app.services.ingest_service import run_ingestion


def _fake_embed_texts(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


def test_ingestion_processes_valid_documents_and_skips_invalid(tmp_path, monkeypatch):
    (tmp_path / "valido.txt").write_text(
        "Este es un documento válido con contenido suficiente para generar chunks.",
        encoding="utf-8",
    )
    (tmp_path / "vacio.txt").write_text("", encoding="utf-8")
    # Las extensiones no soportadas se ignoran silenciosamente en el descubrimiento
    # de archivos (no llegan a load_document ni cuentan como "omitidos con error").
    (tmp_path / "no_soportado.png").write_bytes(b"no es un documento de texto")

    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)

    added_chunks = []

    def fake_add_chunks(chunks, embeddings):
        added_chunks.extend(chunks)

    with patch("app.services.ingest_service.embed_texts", side_effect=_fake_embed_texts), patch(
        "app.services.ingest_service.vector_store.add_chunks", side_effect=fake_add_chunks
    ), patch("app.services.ingest_service.vector_store.reset_collection"):
        result = run_ingestion(rebuild=True, log=lambda *_: None)

    assert result.documents_processed == 1
    assert result.documents_skipped == 1
    assert result.chunks_created > 0
    assert len(added_chunks) == result.chunks_created
    assert len(result.errors) == 1


def test_ingestion_with_no_documents_reports_error(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)

    result = run_ingestion(rebuild=True, log=lambda *_: None)

    assert result.documents_processed == 0
    assert len(result.errors) == 1
