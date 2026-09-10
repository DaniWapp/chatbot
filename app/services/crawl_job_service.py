"""Rastreo de un sitio web como job en segundo plano: corre en un hilo
propio (no bloquea el servidor mientras dura -- un sitio real puede
tomar minutos), reporta progreso consultable desde el panel de
administración, y se puede cancelar entre una página y la siguiente.
app/rag/web_crawler.py hace el rastreo en sí; este módulo lo conecta con
la ingesta real (mismo pipeline que subir un documento a mano) y con el
estado que consulta el panel.

El estado vive en memoria, no en la base de datos -- no sobrevive un
reinicio del servidor. Si eso pasa a mitad de un rastreo, el admin
simplemente lo vuelve a lanzar; las páginas ya indexadas antes del
reinicio quedan indexadas igual (cada una se guarda e ingesta de a una,
no al final)."""
import datetime
import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import settings
from app.rag import web_crawler
from app.services import history
from app.services import ingest_service

# Los PDF/DOCX/XLSX enlazados desde una página se detectan (ver
# web_crawler.BINARY_EXTENSIONS) pero NO se indexan automáticamente en
# esta primera versión -- necesitan el mismo tratamiento de conversión y
# preservación del original que ya tiene la subida manual
# (app/api/routes.py::_upload_document), y replicar eso aquí es un
# alcance aparte. Quedan listados en skipped_binary_urls para que el
# admin los suba a mano si los necesita.


@dataclass
class CrawlJobState:
    job_id: str
    seed_url: str
    status: str = "running"  # running | done | cancelled | error
    pages_indexed: int = 0
    pages_failed: int = 0
    current_url: str = ""
    skipped_binary_urls: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    cancel_requested: bool = False


_jobs: Dict[str, CrawlJobState] = {}
_lock = threading.Lock()


def _job_to_dict(job: CrawlJobState) -> dict:
    return {
        "job_id": job.job_id,
        "seed_url": job.seed_url,
        "status": job.status,
        "pages_indexed": job.pages_indexed,
        "pages_failed": job.pages_failed,
        "current_url": job.current_url,
        "skipped_binary_urls": list(job.skipped_binary_urls),
        "errors": list(job.errors),
    }


def get_job_status(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return _job_to_dict(job) if job else None


def cancel_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.status != "running":
            return False
        job.cancel_requested = True
        return True


def _save_pending_binary_file(url: str, seed_url: str, dependencia_id: Optional[int]) -> None:
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO crawl_pending_files (url, seed_url, dependencia_id, created_at) VALUES (?, ?, ?, ?)",
            (url, seed_url, dependencia_id, datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        conn.commit()


def list_pending_files() -> List[dict]:
    with history.db_lock():
        conn = history.get_connection()
        rows = conn.execute(
            "SELECT id, url, seed_url, dependencia_id, created_at FROM crawl_pending_files ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"id": row[0], "url": row[1], "seed_url": row[2], "dependencia_id": row[3], "created_at": row[4]}
        for row in rows
    ]


def dismiss_pending_file(file_id: int) -> bool:
    with history.db_lock():
        conn = history.get_connection()
        cursor = conn.execute("DELETE FROM crawl_pending_files WHERE id = ?", (file_id,))
        conn.commit()
        return cursor.rowcount > 0


def _index_page(page: "web_crawler.CrawledPage", dependencia_id: Optional[int]) -> None:
    settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.DOCUMENTS_DIR / page.filename
    path.write_text(page.text, encoding="utf-8")
    ingest_service.set_document_dependencia(page.filename, dependencia_id)
    ingest_service.set_document_source_url(page.filename, page.url)
    ingest_service.set_document_downloadable(page.filename, False)
    ingest_service.ingest_single_file(path, dependencia_id, log=lambda *_: None)


def _run_job(
    job_id: str,
    seed_url: str,
    allowed_path_prefix: Optional[str],
    max_depth: int,
    max_pages: int,
    dependencia_id: Optional[int],
) -> None:
    job = _jobs[job_id]
    try:
        for page in web_crawler.crawl_site(
            seed_url,
            allowed_path_prefix=allowed_path_prefix,
            max_depth=max_depth,
            max_pages=max_pages,
            should_stop=lambda: job.cancel_requested,
        ):
            with _lock:
                job.current_url = page.url
            if page.content_bytes is not None:
                with _lock:
                    job.skipped_binary_urls.append(page.url)
                _save_pending_binary_file(page.url, seed_url, dependencia_id)
                continue
            try:
                _index_page(page, dependencia_id)
                with _lock:
                    job.pages_indexed += 1
            except Exception as exc:  # noqa: BLE001 - una página fallida no debe tumbar todo el rastreo
                with _lock:
                    job.pages_failed += 1
                    job.errors.append(f"{page.url}: {exc}")
    except Exception as exc:  # noqa: BLE001 - fallo del rastreo en sí (ej. seed_url inalcanzable)
        with _lock:
            job.status = "error"
            job.errors.append(str(exc))
        return

    with _lock:
        job.status = "cancelled" if job.cancel_requested else "done"


def start_crawl_job(
    seed_url: str,
    allowed_path_prefix: Optional[str],
    max_depth: int,
    max_pages: int,
    dependencia_id: Optional[int],
) -> str:
    job_id = uuid.uuid4().hex
    job = CrawlJobState(job_id=job_id, seed_url=seed_url)
    with _lock:
        _jobs[job_id] = job
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, seed_url, allowed_path_prefix, max_depth, max_pages, dependencia_id),
        daemon=True,
    )
    thread.start()
    return job_id
