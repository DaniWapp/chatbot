"""Orquesta el pipeline RAG completo: recuperación -> contexto -> LLM -> respuesta,
con métricas de tiempo y manejo del caso "sin información suficiente".

Los saludos, agradecimientos y charla casual NO se detectan con reglas propias:
se envían al LLM igual que cualquier otro mensaje (con el contexto de
documentos si se encontró alguno relevante, o vacío si no), y es el propio
modelo quien decide -siguiendo las instrucciones de app/rag/llm.py- si debe
responder de forma cálida a un saludo o usar la frase fija de "no encontré
información" ante una pregunta real sin datos suficientes. Esto evita tener
que mantener expresiones regulares para cada frase nueva."""
import time
from typing import Generator, List, Tuple

from app.config import settings
from app.models.schemas import ChatMetrics, ChatResponse, SourceCitation
from app.rag import llm
from app.rag.retriever import RetrievedChunk, build_context, retrieve, retrieve_below_threshold
from app.services import history as history_service
from app.services import ws_manager


def _looks_too_short_for_citation(question: str) -> bool:
    """Mensajes de 1-2 palabras (ej. "gracias", "ok", "listo") no son
    preguntas reales sobre la facultad; si por casualidad su embedding
    coincide débilmente con algún fragmento (apenas sobre el umbral de
    similitud), no tiene sentido citarlo como fuente."""
    return len(question.strip().split()) < 3


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


ESCALATED_NOTICE = "Tu mensaje fue enviado a tu asesor. Pronto te responderá aquí mismo."


def _save_and_broadcast_turn(session_id: str, question: str, answer: str) -> None:
    """Persiste el turno. Ya no se notifica al panel: mientras el bot sigue
    respondiendo (needs_human es False), la conversación no pertenece a
    ninguna dependencia todavía -- eso solo ocurre al escalar, momento en
    el que sí se avisa al administrador correspondiente (ver
    app/api/routes.py:escalate)."""
    history_service.append_turn(session_id, question, answer)


def _save_and_broadcast_student_message(session_id: str, message: str) -> None:
    """Guarda el mensaje del estudiante en una sesión ya escalada (el bot no
    responde) y avisa en tiempo real al administrador de la dependencia
    asignada (o al general, si no se pudo clasificar) para que lo vea sin
    recargar."""
    created_at = history_service.add_admin_message(session_id, "student", message)
    dependencia_id = history_service.get_session_meta(session_id)["dependencia_id"]
    ws_manager.broadcast_to_dependencia(
        dependencia_id,
        {
            "type": "student_message",
            "session_id": session_id,
            "message": message,
            "created_at": created_at,
        },
    )


def retrieve_context(question: str) -> Tuple[List[RetrievedChunk], float]:
    start = time.perf_counter()
    chunks = retrieve(question)
    retrieval_ms = (time.perf_counter() - start) * 1000
    return chunks, retrieval_ms


_SUGGESTION_CANDIDATE_POOL = 20


def _suggest_clarifications(question: str) -> List[str]:
    """Cuando ya se determinó que no hay información suficiente, revisa si
    hay fragmentos con relación débil (por debajo de SIMILARITY_THRESHOLD)
    para pedirle al LLM hasta 3 preguntas alternativas mejor formuladas.
    Ver llm.suggest_clarifying_questions -- best-effort, nunca lanza.

    Se busca en un top_k más amplio que el de recuperación normal
    (settings.TOP_K, pensado solo para el contexto real de la respuesta):
    con consultas muy abreviadas, el fragmento realmente relevante puede
    quedar fuera del top 4 aunque exista en el índice (ver caso "ing tic").

    A propósito NO se recorta a los 3 candidatos de mayor similitud antes
    de llamar al LLM: en un corpus pequeño con muchas filas de horario, esas
    filas suelen ganar por similitud cruda a un fragmento realmente
    relevante pero más largo/distinto en redacción (como una FAQ), sin
    tener ninguna relación real con la pregunta. Se le pasa el lote
    completo (ya filtrado por SUGGESTION_MIN_SIMILARITY) y es el LLM quien
    decide cuáles -si alguno- están realmente relacionados."""
    weak_candidates = [
        c
        for c in retrieve_below_threshold(question, top_k=_SUGGESTION_CANDIDATE_POOL)
        if c.similarity >= settings.SUGGESTION_MIN_SIMILARITY
    ]
    if not weak_candidates:
        return []
    return llm.suggest_clarifying_questions(question, weak_candidates)


def _draft_response(question: str, conversation_history: List[Tuple[str, str]]) -> Tuple[ChatResponse, str]:
    """Núcleo compartido de recuperación + generación: arma el ChatResponse
    completo (fuentes, sugerencias si no hay información suficiente,
    métricas), sin decidir todavía si hay que revisar la escalación de la
    sesión ni si hay que guardar el turno en el historial -- eso lo decide
    cada llamador (answer_question guarda; draft_answer_for_admin no).
    Devuelve también el texto plano de la respuesta, que answer_question
    necesita para guardar el turno."""
    total_start = time.perf_counter()
    chunks, retrieval_ms = retrieve_context(question)

    context = build_context(chunks) if chunks else ""

    gen_start = time.perf_counter()
    answer_text = llm.generate_answer(question, context, conversation_history)
    generation_ms = (time.perf_counter() - gen_start) * 1000
    total_ms = (time.perf_counter() - total_start) * 1000

    is_no_info = settings.NO_INFO_MESSAGE.strip() in answer_text
    hide_sources = is_no_info or _looks_too_short_for_citation(question)
    suggestions = _suggest_clarifications(question) if is_no_info else []

    response = ChatResponse(
        answer=answer_text,
        sources=[] if hide_sources else _dedup_sources(chunks),
        has_sufficient_info=not is_no_info,
        suggestions=suggestions,
        metrics=ChatMetrics(
            retrieval_ms=round(retrieval_ms, 2),
            generation_ms=round(generation_ms, 2),
            total_ms=round(total_ms, 2),
            chunks_retrieved=len(chunks),
        ),
    )
    return response, answer_text


def answer_question(session_id: str, question: str) -> ChatResponse:
    """Flujo completo sin streaming (usado por evaluación/tests y como fallback)."""
    if history_service.needs_human(session_id):
        _save_and_broadcast_student_message(session_id, question)
        return ChatResponse(
            answer=ESCALATED_NOTICE,
            sources=[],
            has_sufficient_info=True,
            escalated=True,
            metrics=ChatMetrics(retrieval_ms=0.0, generation_ms=0.0, total_ms=0.0, chunks_retrieved=0),
        )

    conversation_history = history_service.get_history(session_id)
    response, answer_text = _draft_response(question, conversation_history)
    _save_and_broadcast_turn(session_id, question, answer_text)
    return response


def draft_answer_for_admin(session_id: str, question: str) -> ChatResponse:
    """Herramienta de apoyo para el asesor humano: le pide al chatbot un
    borrador de respuesta para una pregunta -que puede ser una reescritura
    mejorada de lo que escribió el estudiante- mientras atiende una
    conversación ya escalada.

    A diferencia de answer_question(), a propósito NO revisa needs_human()
    (la sesión SIEMPRE está escalada cuando se usa esta herramienta -- por
    eso el asesor necesita ayuda) y NO guarda nada en el historial del
    estudiante: es una consulta de solo lectura que el asesor revisa antes
    de decidir usarla (copiándola a su campo de respuesta) o descartarla."""
    conversation_history = history_service.get_history(session_id)
    response, _ = _draft_response(question, conversation_history)
    return response


def stream_answer(session_id: str, question: str) -> Generator[dict, None, None]:
    """Flujo con streaming: primero recupera contexto, luego va emitiendo eventos
    (tipo 'meta' con fuentes/métricas parciales, 'delta' con texto incremental,
    'done' al final) para que el frontend pueda usar Server-Sent Events."""
    if history_service.needs_human(session_id):
        _save_and_broadcast_student_message(session_id, question)
        yield {"type": "meta", "sources": [], "has_sufficient_info": True}
        yield {"type": "escalated", "text": ESCALATED_NOTICE}
        yield {
            "type": "done",
            "metrics": {"retrieval_ms": 0.0, "generation_ms": 0.0, "total_ms": 0.0, "chunks_retrieved": 0},
        }
        return

    chunks, retrieval_ms = retrieve_context(question)

    context = build_context(chunks) if chunks else ""
    conversation_history = history_service.get_history(session_id)
    sources = _dedup_sources(chunks) if chunks and not _looks_too_short_for_citation(question) else []

    yield {"type": "meta", "sources": [s.model_dump() for s in sources], "has_sufficient_info": bool(chunks)}

    gen_start = time.perf_counter()
    full_answer = ""
    for delta in llm.stream_answer(question, context, conversation_history):
        full_answer += delta
        yield {"type": "delta", "text": delta}
    generation_ms = (time.perf_counter() - gen_start) * 1000

    _save_and_broadcast_turn(session_id, question, full_answer)

    is_no_info = settings.NO_INFO_MESSAGE.strip() in full_answer
    suggestions = _suggest_clarifications(question) if is_no_info else []

    yield {
        "type": "done",
        "suggestions": suggestions,
        "metrics": {
            "retrieval_ms": round(retrieval_ms, 2),
            "generation_ms": round(generation_ms, 2),
            "total_ms": round(retrieval_ms + generation_ms, 2),
            "chunks_retrieved": len(chunks),
        },
    }
