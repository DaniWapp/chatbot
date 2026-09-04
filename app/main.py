"""Punto de entrada de la aplicación: API REST + servido de la interfaz web estática."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import _perform_reassignment
from app.api.routes import router as api_router
from app.config import settings
from app.services import history as history_service
from app.services import ws_manager

logger = logging.getLogger(__name__)

FRONTEND_DIR = settings.BASE_DIR / "frontend"


async def _history_backup_loop() -> None:
    """Respalda history.db cada HISTORY_BACKUP_INTERVAL_SECONDS mientras el
    servidor esté corriendo. backup_now() hace I/O de archivo bloqueante,
    así que corre en un hilo aparte para no congelar el event loop (donde
    también viven las conexiones WebSocket)."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, history_service.backup_now)
        except Exception:
            logger.exception("Fallo al respaldar history.db")
        await asyncio.sleep(settings.HISTORY_BACKUP_INTERVAL_SECONDS)


async def _auto_escalation_loop() -> None:
    """Cada AUTO_ESCALATION_CHECK_INTERVAL_SECONDS, redirige automáticamente
    hacia el administrador general las conversaciones que llevan más de
    AUTO_ESCALATION_TIMEOUT_SECONDS asignadas a una dependencia sin que
    nadie haya respondido todavía (ver
    history_service.find_unattended_sessions). Reusa _perform_reassignment
    -- el mismo helper que usa la redirección manual -- para que el
    estudiante y los paneles se enteren exactamente igual."""
    while True:
        try:
            for item in history_service.find_unattended_sessions(settings.AUTO_ESCALATION_TIMEOUT_SECONDS):
                _perform_reassignment(item["session_id"], None, item["dependencia_id"])
        except Exception:
            logger.exception("Fallo en el auto-escalamiento por SLA vencido")
        await asyncio.sleep(settings.AUTO_ESCALATION_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Guarda una referencia al event loop asíncrono para que chat_service
    # (código síncrono, corre en threadpool) pueda transmitir eventos a los
    # paneles de control conectados por WebSocket.
    ws_manager.set_event_loop(asyncio.get_running_loop())

    backup_task = asyncio.create_task(_history_backup_loop())
    auto_escalation_task = asyncio.create_task(_auto_escalation_loop())
    try:
        yield
    finally:
        backup_task.cancel()
        auto_escalation_task.cancel()


app = FastAPI(
    title="Chatbot Facultad de Ingeniería",
    description="Asistente RAG sobre documentos oficiales de la facultad.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS restringido a los orígenes configurados en ALLOWED_ORIGINS (.env):
# ahora se manejan datos reales de estudiantes (nombre, correo, mensajes),
# así que un CORS abierto expondría todo a cualquier sitio web.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    # No-cache en el HTML: sin esto, el navegador puede quedarse con una
    # versión vieja de la página (y por lo tanto con enlaces viejos a
    # style.css/script.js) y no darse cuenta de que hay una nueva.
    _NO_CACHE_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/")
    def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"), headers=_NO_CACHE_HEADERS)

    @app.get("/panel")
    def serve_panel():
        return FileResponse(str(FRONTEND_DIR / "panel.html"), headers=_NO_CACHE_HEADERS)

    @app.get("/root")
    def serve_root_panel():
        return FileResponse(str(FRONTEND_DIR / "root.html"), headers=_NO_CACHE_HEADERS)
