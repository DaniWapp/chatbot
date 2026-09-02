"""Rutas de la API: /api/chat (síncrono y streaming), /api/ingest, /api/health."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.schemas import ChatRequest, ChatResponse, HealthResponse, IngestResponse
from app.rag import vector_store
from app.services import chat_service
from app.services.ingest_service import run_ingestion

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        indexed = vector_store.count()
    except Exception:
        indexed = 0
    return HealthResponse(
        status="ok",
        groq_configured=bool(settings.GROQ_API_KEY),
        documents_indexed=indexed,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY no configurada en el servidor. Revisa el archivo .env.",
        )
    try:
        return chat_service.answer_question(payload.session_id, payload.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error generando la respuesta: {exc}") from exc


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    """Igual que /chat pero como Server-Sent Events, para mostrar la respuesta
    apareciendo progresivamente en la interfaz (mejor percepción de velocidad)."""
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY no configurada en el servidor. Revisa el archivo .env.",
        )

    def event_generator():
        try:
            for event in chat_service.stream_answer(payload.session_id, payload.message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            error_event = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/ingest", response_model=IngestResponse)
def ingest() -> IngestResponse:
    """Reconstruye el índice vectorial a partir de los documentos en /documents.

    Pensado para uso ocasional desde una interfaz de administración simple;
    para ingestión rutinaria se recomienda `python scripts/ingest.py`.
    """
    result = run_ingestion(rebuild=True, log=lambda *_: None)
    return IngestResponse(
        status="ok" if result.documents_processed > 0 else "sin_documentos",
        documents_processed=result.documents_processed,
        chunks_created=result.chunks_created,
        errors=result.errors,
    )
