"""Orquesta el pipeline RAG completo: recuperación -> contexto -> LLM -> respuesta,
con métricas de tiempo y manejo del caso "sin información suficiente"."""
import re
import time
from typing import Generator, List, Optional, Tuple

from app.config import settings
from app.models.schemas import ChatMetrics, ChatResponse, SourceCitation
from app.rag import llm
from app.rag.retriever import RetrievedChunk, build_context, retrieve
from app.services import history as history_service

# Saludos y agradecimientos se responden directamente, sin pasar por la
# búsqueda semántica ni el LLM: no son preguntas sobre la facultad, así que
# no tiene sentido evaluarlos contra el umbral de relevancia (eso llevaría a
# responder "no encontré información" ante un simple "hola").
_GREETING_RE = re.compile(
    r"^("
    r"hol[ai]+s?"                                          # hola, holis, holaa, holii...
    r"|ol[ai]+s?"                                           # ola, olis (sin "h")
    r"|buen[oa]s?(\s+d[ií]as?|\s+tardes?|\s+noches?)?"      # buenas, buenos días...
    r"|hey+|ey+"                                            # hey, ey
    r"|qu?[eé]?\s*(tal|más|mas|hubo|onda)"                  # qué tal, qué más, q hubo, qué onda
    r"|qui?ubo|quihubo"                                     # quiubo, quihubo
    r"|saludos|hi|hello"
    r")[\s!.,¡¿?]*$",
    re.IGNORECASE,
)
# Cubre las variantes coloquiales más comunes en español, no todas las
# posibles (es una lista, no un modelo de lenguaje): si aparece una nueva
# variante frecuente durante las pruebas, se agrega aquí.
_THANKS_RE = re.compile(r"^(muchas\s+|mil\s+)?gracias[\s!.,¡¿?]*$", re.IGNORECASE)

_GREETING_REPLY = (
    "¡Hola! Soy el asistente virtual de la Facultad de Ingeniería. Puedo ayudarte "
    "con preguntas sobre reglamentos, matrículas, calendario académico, requisitos "
    "de grado y otros procesos académicos. ¿En qué puedo ayudarte?"
)
_THANKS_REPLY = "¡Con gusto! Si tienes otra pregunta sobre la facultad, aquí estoy."


def _smalltalk_reply(message: str) -> Optional[str]:
    text = message.strip()
    if _GREETING_RE.match(text):
        return _GREETING_REPLY
    if _THANKS_RE.match(text):
        return _THANKS_REPLY
    return None


def _dedup_sources(chunks: List[RetrievedChunk]) -> List[SourceCitation]:
    """Colapsa varios chunks de la misma página/documento en una sola cita,
    conservando la similitud más alta encontrada."""
    best: dict = {}
    for c in chunks:
        key = (c.document, c.page)
        if key not in best or c.similarity > best[key].similarity:
            best[key] = SourceCitation(
                document=c.document, page=c.page, chunk_id=c.chunk_id, similarity=round(c.similarity, 4)
            )
    return sorted(best.values(), key=lambda s: s.similarity, reverse=True)


def retrieve_context(question: str) -> Tuple[List[RetrievedChunk], float]:
    start = time.perf_counter()
    chunks = retrieve(question)
    retrieval_ms = (time.perf_counter() - start) * 1000
    return chunks, retrieval_ms


def answer_question(session_id: str, question: str) -> ChatResponse:
    """Flujo completo sin streaming (usado por evaluación/tests y como fallback)."""
    smalltalk = _smalltalk_reply(question)
    if smalltalk:
        history_service.append_turn(session_id, question, smalltalk)
        return ChatResponse(
            answer=smalltalk,
            sources=[],
            has_sufficient_info=True,
            metrics=ChatMetrics(retrieval_ms=0.0, generation_ms=0.0, total_ms=0.0, chunks_retrieved=0),
        )

    total_start = time.perf_counter()
    chunks, retrieval_ms = retrieve_context(question)

    if not chunks:
        total_ms = (time.perf_counter() - total_start) * 1000
        return ChatResponse(
            answer=settings.NO_INFO_MESSAGE,
            sources=[],
            has_sufficient_info=False,
            metrics=ChatMetrics(
                retrieval_ms=round(retrieval_ms, 2),
                generation_ms=0.0,
                total_ms=round(total_ms, 2),
                chunks_retrieved=0,
            ),
        )

    context = build_context(chunks)
    conversation_history = history_service.get_history(session_id)

    gen_start = time.perf_counter()
    answer_text = llm.generate_answer(question, context, conversation_history)
    generation_ms = (time.perf_counter() - gen_start) * 1000

    history_service.append_turn(session_id, question, answer_text)
    total_ms = (time.perf_counter() - total_start) * 1000

    is_no_info = settings.NO_INFO_MESSAGE.strip() in answer_text

    return ChatResponse(
        answer=answer_text,
        sources=[] if is_no_info else _dedup_sources(chunks),
        has_sufficient_info=not is_no_info,
        metrics=ChatMetrics(
            retrieval_ms=round(retrieval_ms, 2),
            generation_ms=round(generation_ms, 2),
            total_ms=round(total_ms, 2),
            chunks_retrieved=len(chunks),
        ),
    )


def stream_answer(session_id: str, question: str) -> Generator[dict, None, None]:
    """Flujo con streaming: primero recupera contexto, luego va emitiendo eventos
    (tipo 'meta' con fuentes/métricas parciales, 'delta' con texto incremental,
    'done' al final) para que el frontend pueda usar Server-Sent Events."""
    smalltalk = _smalltalk_reply(question)
    if smalltalk:
        yield {"type": "meta", "sources": [], "has_sufficient_info": True}
        yield {"type": "delta", "text": smalltalk}
        yield {
            "type": "done",
            "metrics": {"retrieval_ms": 0.0, "generation_ms": 0.0, "total_ms": 0.0, "chunks_retrieved": 0},
        }
        history_service.append_turn(session_id, question, smalltalk)
        return

    chunks, retrieval_ms = retrieve_context(question)

    if not chunks:
        yield {"type": "meta", "sources": [], "has_sufficient_info": False}
        yield {"type": "delta", "text": settings.NO_INFO_MESSAGE}
        yield {
            "type": "done",
            "metrics": {
                "retrieval_ms": round(retrieval_ms, 2),
                "generation_ms": 0.0,
                "total_ms": round(retrieval_ms, 2),
                "chunks_retrieved": 0,
            },
        }
        history_service.append_turn(session_id, question, settings.NO_INFO_MESSAGE)
        return

    context = build_context(chunks)
    conversation_history = history_service.get_history(session_id)
    sources = _dedup_sources(chunks)

    yield {"type": "meta", "sources": [s.model_dump() for s in sources], "has_sufficient_info": True}

    gen_start = time.perf_counter()
    full_answer = ""
    for delta in llm.stream_answer(question, context, conversation_history):
        full_answer += delta
        yield {"type": "delta", "text": delta}
    generation_ms = (time.perf_counter() - gen_start) * 1000

    history_service.append_turn(session_id, question, full_answer)

    yield {
        "type": "done",
        "metrics": {
            "retrieval_ms": round(retrieval_ms, 2),
            "generation_ms": round(generation_ms, 2),
            "total_ms": round(retrieval_ms + generation_ms, 2),
            "chunks_retrieved": len(chunks),
        },
    }
