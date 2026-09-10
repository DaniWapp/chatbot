"""Pruebas del job de rastreo en segundo plano
(app/services/crawl_job_service.py). web_crawler.crawl_site e
ingest_service.ingest_single_file se mockean -- esto prueba la
orquestación (progreso, cancelación, manejo de errores por página), no
el rastreo real ni el pipeline de embeddings."""
import threading
import time
import uuid
from unittest.mock import patch

from app.rag.web_crawler import CrawledPage
from app.services import crawl_job_service, ingest_service


def _wait_until_finished(job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = crawl_job_service.get_job_status(job_id)
        if status["status"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError(f"El job {job_id} no terminó dentro de {timeout}s")


def test_get_job_status_returns_none_for_unknown_job():
    assert crawl_job_service.get_job_status("no-existe") is None


def test_cancel_job_returns_false_for_unknown_job():
    assert crawl_job_service.cancel_job("no-existe") is False


@patch("app.services.ingest_service.vector_store.add_chunks")
@patch("app.services.ingest_service.embed_texts", return_value=[[0.1, 0.2, 0.3]])
@patch("app.rag.web_crawler.crawl_site")
def test_run_job_indexes_text_pages_and_reports_progress(mock_crawl, mock_embed, mock_add_chunks, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)
    unique = uuid.uuid4().hex
    mock_crawl.return_value = iter(
        [
            CrawledPage(url="https://sitio.edu/cucuta", filename=f"web-home-{unique}.txt", text="Contenido de inicio."),
            CrawledPage(
                url="https://sitio.edu/cucuta/ingenieria",
                filename=f"web-ingenieria-{unique}.txt",
                text="Contenido de ingeniería.",
            ),
        ]
    )

    job_id = crawl_job_service.start_crawl_job(
        "https://sitio.edu/cucuta/", allowed_path_prefix="/cucuta", max_depth=1, max_pages=10, dependencia_id=None
    )
    status = _wait_until_finished(job_id)

    assert status["status"] == "done"
    assert status["pages_indexed"] == 2
    assert status["pages_failed"] == 0
    assert (tmp_path / f"web-home-{unique}.txt").read_text(encoding="utf-8") == "Contenido de inicio."
    assert ingest_service.get_document_source_url(f"web-home-{unique}.txt") == "https://sitio.edu/cucuta"
    assert ingest_service.get_document_downloadable(f"web-home-{unique}.txt") is False


@patch("app.rag.web_crawler.crawl_site")
def test_run_job_skips_binary_pages_without_indexing(mock_crawl, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)
    mock_crawl.return_value = iter(
        [CrawledPage(url="https://sitio.edu/cucuta/res.pdf", filename="web-res.pdf", content_bytes=b"%PDF-1.4")]
    )

    job_id = crawl_job_service.start_crawl_job(
        "https://sitio.edu/cucuta/", allowed_path_prefix="/cucuta", max_depth=1, max_pages=10, dependencia_id=None
    )
    status = _wait_until_finished(job_id)

    assert status["status"] == "done"
    assert status["pages_indexed"] == 0
    assert status["skipped_binary_urls"] == ["https://sitio.edu/cucuta/res.pdf"]
    assert not (tmp_path / "web-res.pdf").exists()


@patch("app.services.ingest_service.vector_store.add_chunks")
@patch("app.services.ingest_service.embed_texts", return_value=[[0.1, 0.2, 0.3]])
@patch("app.rag.web_crawler.crawl_site")
def test_run_job_continues_after_a_single_page_failure(mock_crawl, mock_embed, mock_add_chunks, tmp_path, monkeypatch):
    """Una página que falla al indexarse (ej. no genera texto util) no debe
    tumbar el resto del rastreo."""
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)
    unique = uuid.uuid4().hex
    mock_crawl.return_value = iter(
        [
            CrawledPage(url="https://sitio.edu/cucuta/mala", filename=f"web-mala-{unique}.txt", text=None),
            CrawledPage(url="https://sitio.edu/cucuta/buena", filename=f"web-buena-{unique}.txt", text="Contenido real."),
        ]
    )

    job_id = crawl_job_service.start_crawl_job(
        "https://sitio.edu/cucuta/", allowed_path_prefix="/cucuta", max_depth=1, max_pages=10, dependencia_id=None
    )
    status = _wait_until_finished(job_id)

    assert status["status"] == "done"
    assert status["pages_indexed"] == 1
    assert status["pages_failed"] == 1
    assert len(status["errors"]) == 1


@patch("app.rag.web_crawler.crawl_site")
def test_run_job_reports_error_status_when_crawl_itself_fails(mock_crawl, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)

    def _raise(*args, **kwargs):
        raise ConnectionError("no se pudo conectar")
        yield  # pragma: no cover - hace de esta func un generador, nunca se llega aquí

    mock_crawl.side_effect = _raise

    job_id = crawl_job_service.start_crawl_job(
        "https://sitio-inexistente.edu/", allowed_path_prefix="/", max_depth=1, max_pages=10, dependencia_id=None
    )
    status = _wait_until_finished(job_id)

    assert status["status"] == "error"
    assert any("no se pudo conectar" in e for e in status["errors"])


@patch("app.services.ingest_service.vector_store.add_chunks")
@patch("app.services.ingest_service.embed_texts", return_value=[[0.1, 0.2, 0.3]])
@patch("app.rag.web_crawler.crawl_site")
def test_cancel_job_stops_early_and_marks_cancelled(mock_crawl, mock_embed, mock_add_chunks, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)
    # Sincroniza con el hilo en segundo plano para que cancel_job() se
    # llame de forma determinista ENTRE la primera y la segunda página --
    # sin esto, la carrera entre el hilo y el hilo de la prueba haría el
    # resultado impredecible (podría procesar las dos antes de cancelar).
    first_page_done = threading.Event()
    can_continue = threading.Event()

    def _slow_pages(*args, **kwargs):
        should_stop = kwargs["should_stop"]
        yield CrawledPage(url="https://sitio.edu/cucuta", filename="web-1.txt", text="Uno.")
        first_page_done.set()
        can_continue.wait(timeout=5)
        if should_stop():
            return
        yield CrawledPage(url="https://sitio.edu/cucuta/2", filename="web-2.txt", text="Dos.")

    mock_crawl.side_effect = _slow_pages

    job_id = crawl_job_service.start_crawl_job(
        "https://sitio.edu/cucuta/", allowed_path_prefix="/cucuta", max_depth=1, max_pages=10, dependencia_id=None
    )
    assert first_page_done.wait(timeout=5)
    crawl_job_service.cancel_job(job_id)
    can_continue.set()
    status = _wait_until_finished(job_id)

    assert status["status"] == "cancelled"
    assert status["pages_indexed"] == 1
