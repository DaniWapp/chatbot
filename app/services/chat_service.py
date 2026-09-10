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
from typing import Generator, List, Optional, Tuple

from app.config import settings
from app.models.schemas import ChatMetrics, ChatResponse, SourceCitation
from app.rag import llm, reranker
from app.rag.retriever import (
    RetrievedChunk,
    build_context,
    drop_superseded_by_vigencia,
    retrieve,
    retrieve_below_threshold,
)
from app.services import answer_cache_service
from app.services import history as history_service
from app.services import hostility_service
from app.services import ingest_service
from app.services import ws_manager


def _needs_query_rewrite(chunks: List[RetrievedChunk]) -> bool:
    """Si la búsqueda con el mensaje tal cual no encontró NADA, vale la
    pena intentar una reformulación antes de darse por vencido -- ver
    _try_multi_query_rewrite para cuál de las dos reformulaciones posibles
    aplica (expandir con historial, o condensar rodeos/cortesías)."""
    return not chunks


# Sin historial de conversación, no vale la pena pedirle a Groq que
# condense mensajes cortos (saludos, "gracias", etc.): esos legítimamente
# no encuentran nada porque no son una pregunta real, no porque el
# embedding se haya diluido -- gastar una llamada ahí sería el caso común
# que justo se quiere evitar. Una pregunta realmente elaborada (el caso
# real que motivó esto, ver llm.py::condense_query_for_search) es, por
# definición, larga -- 6 palabras es un piso bajo a propósito, para no
# bloquear preguntas cortas pero genuinas.
_MIN_WORDS_FOR_CONDENSATION = 6


def _worth_condensing(question: str) -> bool:
    return len(question.split()) >= _MIN_WORDS_FOR_CONDENSATION


# Un seguimiento corto ("precio", "¿y el costo?") con conversación previa
# es sospechoso de ser elíptico -- depende del tema de turnos anteriores.
# Caso real que motivó esto: "qué precio tiene?" tras hablar de una
# carrera encontró 1 fragmento (no cero) de puro ruido -- una fila suelta
# de una matriz bibliográfica sin ninguna relación, que pasó
# RERANK_MIN_SCORE por casualidad (confianza real medida: 0.10). Como el
# disparador solo miraba si la búsqueda encontró CERO resultados, ese
# ruido no vacío bloqueaba por completo la reformulación con historial,
# aunque el caso es exactamente el que existe para resolver. Por eso
# ahora también se intenta reformular cuando la pregunta es corta y hay
# historial, sin importar si la búsqueda con el mensaje tal cual ya trajo
# algo -- si ese algo era en realidad mejor, la reformulación no lo pierde
# (ver _try_multi_query_rewrite: solo reemplaza el resultado si encuentra
# algo que sí pasa el re-ranking, nunca lo empeora).
_MAX_WORDS_FOR_FOLLOWUP_EXPANSION = 5


def _looks_like_a_followup(question: str) -> bool:
    return len(question.split()) <= _MAX_WORDS_FOR_FOLLOWUP_EXPANSION


def _filter_chunks_by_used_sources(
    chunks: List[RetrievedChunk], used_document_names: Optional[List[str]]
) -> List[RetrievedChunk]:
    """Se queda solo con los chunks de los documentos que el LLM reportó
    haber usado de verdad (ver llm.extract_used_sources). Si no vino la
    lista, o ninguno de los nombres coincide con un documento realmente
    recuperado (ej. el LLM escribió el nombre distinto), se muestran
    todos los recuperados -- igual que antes de este cambio, nunca peor."""
    if not used_document_names:
        return chunks
    filtered = [c for c in chunks if c.document in used_document_names]
    return filtered or chunks


def _dedup_sources(chunks: List[RetrievedChunk]) -> List[SourceCitation]:
    """Colapsa varios chunks de la misma página/documento en una sola cita,
    conservando la similitud más alta encontrada."""
    best: dict = {}
    downloadable_by_document: dict = {}
    for c in chunks:
        key = (c.document, c.page)
        if key not in best or c.similarity > best[key].similarity:
            if c.document not in downloadable_by_document:
                downloadable_by_document[c.document] = ingest_service.get_document_downloadable(c.document)
            best[key] = SourceCitation(
                document=c.document,
                page=c.page,
                chunk_id=c.chunk_id,
                similarity=round(c.similarity, 4),
                downloadable=downloadable_by_document[c.document],
            )
    return sorted(best.values(), key=lambda s: s.similarity, reverse=True)


ESCALATED_NOTICE = "Tu mensaje fue enviado a tu asesor. Pronto te responderá aquí mismo."


def _save_and_broadcast_turn(
    session_id: str,
    question: str,
    answer: str,
    sources: Optional[List[SourceCitation]] = None,
    suggestions: Optional[List[str]] = None,
    dependencia_id: Optional[int] = None,
) -> str:
    """Persiste el turno y devuelve su created_at -- el cliente lo necesita
    para poder identificar después esta respuesta puntual al dar feedback
    (ver app/services/history.py::record_feedback, turns no expone su id
    autoincremental). Ya no se notifica al panel: mientras el bot sigue
    respondiendo (needs_human es False), la conversación no pertenece a
    ninguna dependencia todavía -- eso solo ocurre al escalar, momento en
    el que sí se avisa al administrador correspondiente (ver
    app/api/routes.py:escalate).

    sources/suggestions/dependencia_id se guardan junto al turno para poder
    reconstruir la respuesta completa (fuentes, sugerencias, aviso de
    filtro) al recargar el historial -- ver history.py::append_turn."""
    return history_service.append_turn(
        session_id,
        question,
        answer,
        sources=[s.model_dump() for s in sources] if sources else None,
        suggestions=suggestions or None,
        dependencia_id=dependencia_id,
    )


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


def retrieve_context(question: str, dependencia_id: Optional[int] = None) -> Tuple[List[RetrievedChunk], float]:
    start = time.perf_counter()
    chunks = retrieve(question, dependencia_id=dependencia_id)
    retrieval_ms = (time.perf_counter() - start) * 1000
    return chunks, retrieval_ms


def _try_multi_query_rewrite(
    question: str,
    chunks: List[RetrievedChunk],
    retrieval_ms: float,
    conversation_history: List[Tuple[str, str]],
    dependencia_id: Optional[int] = None,
) -> Tuple[List[RetrievedChunk], str, float]:
    """Si la búsqueda con el mensaje tal cual no encontró nada, o parece
    un seguimiento corto que depende del historial, pide reformulaciones
    autónomas de la pregunta (multi-query retrieval: distintas formulaciones pueden
    coincidir con fragmentos distintos del índice) y busca con cada una,
    combinando los fragmentos sin duplicar por chunk_id y re-rankeando el
    conjunto combinado una vez más para quedarse con los TOP_K realmente
    mejores entre todas las variaciones.

    Hay dos formas de reformular, mutuamente excluyentes, según si hay
    conversación previa:
    - Con historial: EXPANDE la pregunta incorporando el tema implícito
      de turnos anteriores (llm.rewrite_query_variations) -- caso
      original: un seguimiento corto como "precio" tras hablar de
      "Ingeniería en TIC". Se intenta si la búsqueda no encontró nada, O
      si la pregunta es corta (_looks_like_a_followup) aunque sí haya
      encontrado algo -- caso real: "qué precio tiene?" encontró 1
      fragmento de puro ruido (una fila de una matriz bibliográfica) en
      vez de cero, lo que antes bloqueaba la reformulación por completo.
    - Sin historial: CONDENSA la pregunta tal cual, quitando rodeos y
      cortesías que diluyen el embedding (llm.condense_query_for_search)
      -- caso real verificado: una pregunta con cortesías/dudas no pasa
      el umbral de relevancia por sí sola aunque el tema sí esté en los
      documentos. Solo se intenta si la búsqueda no encontró nada Y la
      pregunta tiene un tamaño mínimo (_worth_condensing) -- un saludo
      corto sin historial legítimamente no encuentra nada, y no vale la
      pena gastar una llamada a Groq ahí.

    Devuelve (chunks, pregunta_para_retrieval_y_caché, retrieval_ms ya
    incluyendo el costo de esto). Si no hacía falta reformular, o ninguna
    variación encontró nada mejor, devuelve los chunks y la pregunta
    original sin cambios -- nunca deja la búsqueda peor de lo que ya
    estaba (la reformulación solo REEMPLAZA el resultado si encuentra algo
    que sí pasa el re-ranking, ver más abajo)."""
    needs_retry = _needs_query_rewrite(chunks) or (
        bool(conversation_history) and _looks_like_a_followup(question)
    )
    if not needs_retry:
        return chunks, question, retrieval_ms

    if not conversation_history and not _worth_condensing(question):
        return chunks, question, retrieval_ms

    rewrite_start = time.perf_counter()
    if conversation_history:
        variations = llm.rewrite_query_variations(question, conversation_history)
    else:
        variations = llm.condense_query_for_search(question)
    combined: List[RetrievedChunk] = []
    seen_ids = set()
    for variation in variations:
        if variation.strip().lower() == question.strip().lower():
            continue
        variation_chunks, _ = retrieve_context(variation, dependencia_id=dependencia_id)
        for c in variation_chunks:
            if c.chunk_id not in seen_ids:
                seen_ids.add(c.chunk_id)
                combined.append(c)

    # Re-rankear (y filtrar vigencia) contra la MEJOR VARIACIÓN, no contra
    # la pregunta original -- bug real encontrado al verificar esto con el
    # cross-encoder de verdad (no el mock de las pruebas): para la pregunta
    # elaborada que motivó condense_query_for_search, la variante
    # encontraba los 3 chunks correctos, pero re-rankearlos contra la
    # pregunta original (con los rodeos) los hacía sobrevivir 0 -- el
    # mismo problema de dilución que afecta al embedding afecta también el
    # juicio del cross-encoder. Con un seguimiento corto tipo "precio" esto
    # pasaba desapercibido (una palabra sola no diluye tanto), pero es el
    # mismo bug.
    best_variation = variations[0] if variations else question
    retrieval_question = question
    if combined:
        if settings.RERANK_ENABLED:
            combined = reranker.rerank(best_variation, combined, settings.TOP_K, settings.RERANK_MIN_SCORE)
        else:
            combined = combined[: settings.TOP_K]
        combined = drop_superseded_by_vigencia(best_variation, combined)
    if combined:
        chunks = combined
        retrieval_question = best_variation

    retrieval_ms += (time.perf_counter() - rewrite_start) * 1000
    return chunks, retrieval_question, retrieval_ms


_SUGGESTION_CANDIDATE_POOL = 20


def _suggest_clarifications(question: str, dependencia_id: Optional[int] = None) -> List[str]:
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
        for c in retrieve_below_threshold(question, top_k=_SUGGESTION_CANDIDATE_POOL, dependencia_id=dependencia_id)
        if c.similarity >= settings.SUGGESTION_MIN_SIMILARITY
    ]
    if not weak_candidates:
        return []
    return llm.suggest_clarifying_questions(question, weak_candidates)


def _draft_response(
    session_id: str,
    question: str,
    conversation_history: List[Tuple[str, str]],
    dependencia_id: Optional[int] = None,
) -> Tuple[ChatResponse, str]:
    """Núcleo compartido de recuperación + generación: arma el ChatResponse
    completo (fuentes, sugerencias si no hay información suficiente,
    métricas), sin decidir todavía si hay que revisar la escalación de la
    sesión ni si hay que guardar el turno en el historial -- eso lo decide
    cada llamador (answer_question guarda; draft_answer_for_admin no).
    Devuelve también el texto plano de la respuesta, que answer_question
    necesita para guardar el turno.

    dependencia_id: la dependencia elegida por el estudiante en el
    selector del chat (None = buscar en todo), ver
    app/rag/retriever.py::retrieve()."""
    total_start = time.perf_counter()
    chunks, retrieval_ms = retrieve_context(question, dependencia_id=dependencia_id)
    chunks, retrieval_question, retrieval_ms = _try_multi_query_rewrite(
        question, chunks, retrieval_ms, conversation_history, dependencia_id=dependencia_id
    )

    cached_answer = answer_cache_service.try_get_cached_answer(retrieval_question, chunks)
    gen_start = time.perf_counter()
    if cached_answer is not None:
        answer_text = cached_answer
    else:
        context = build_context(chunks) if chunks else ""
        answer_text = llm.generate_answer(question, context, conversation_history)
    generation_ms = (time.perf_counter() - gen_start) * 1000
    total_ms = (time.perf_counter() - total_start) * 1000

    is_no_info = settings.NO_INFO_MESSAGE.strip() in answer_text
    suggestions = _suggest_clarifications(question, dependencia_id=dependencia_id) if is_no_info else []

    if cached_answer is None:
        answer_cache_service.maybe_store_answer(retrieval_question, chunks, answer_text)

    # Se cachea el texto crudo (con la línea FUENTES_USADAS) arriba, para
    # que una respuesta repetida servida desde caché también se pueda
    # filtrar -- recién ahora se separa esa línea del texto visible.
    answer_text, used_sources = llm.extract_used_sources(answer_text)
    relevant_chunks = _filter_chunks_by_used_sources(chunks, used_sources)

    history_service.record_chat_metrics(
        session_id,
        round(retrieval_ms, 2),
        round(generation_ms, 2),
        round(total_ms, 2),
        len(chunks),
        cache_hit=cached_answer is not None,
    )

    response = ChatResponse(
        answer=answer_text,
        sources=[] if is_no_info else _dedup_sources(relevant_chunks),
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


def answer_question(session_id: str, question: str, dependencia_id: Optional[int] = None) -> ChatResponse:
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

    hostility_notice = hostility_service.check_and_intercept(session_id, question)
    if hostility_notice is not None:
        response = ChatResponse(
            answer=hostility_notice,
            sources=[],
            has_sufficient_info=True,
            metrics=ChatMetrics(retrieval_ms=0.0, generation_ms=0.0, total_ms=0.0, chunks_retrieved=0),
        )
        response.turn_created_at = _save_and_broadcast_turn(session_id, question, hostility_notice)
        return response

    conversation_history = history_service.get_history(session_id)
    response, answer_text = _draft_response(session_id, question, conversation_history, dependencia_id=dependencia_id)
    response.turn_created_at = _save_and_broadcast_turn(
        session_id,
        question,
        answer_text,
        sources=response.sources,
        suggestions=response.suggestions,
        dependencia_id=dependencia_id,
    )
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
    response, _ = _draft_response(session_id, question, conversation_history)
    return response


def stream_answer(
    session_id: str, question: str, dependencia_id: Optional[int] = None
) -> Generator[dict, None, None]:
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

    hostility_notice = hostility_service.check_and_intercept(session_id, question)
    if hostility_notice is not None:
        turn_created_at = _save_and_broadcast_turn(session_id, question, hostility_notice)
        yield {"type": "meta", "sources": [], "has_sufficient_info": True}
        yield {"type": "delta", "text": hostility_notice}
        yield {
            "type": "done",
            "suggestions": [],
            "turn_created_at": turn_created_at,
            "metrics": {"retrieval_ms": 0.0, "generation_ms": 0.0, "total_ms": 0.0, "chunks_retrieved": 0},
        }
        return

    chunks, retrieval_ms = retrieve_context(question, dependencia_id=dependencia_id)
    conversation_history = history_service.get_history(session_id)
    chunks, retrieval_question, retrieval_ms = _try_multi_query_rewrite(
        question, chunks, retrieval_ms, conversation_history, dependencia_id=dependencia_id
    )

    sources = _dedup_sources(chunks) if chunks else []

    yield {"type": "meta", "sources": [s.model_dump() for s in sources], "has_sufficient_info": bool(chunks)}

    cached_answer = answer_cache_service.try_get_cached_answer(retrieval_question, chunks)
    gen_start = time.perf_counter()
    if cached_answer is not None:
        full_answer = cached_answer
        yield {"type": "delta", "text": full_answer}
    else:
        context = build_context(chunks) if chunks else ""
        full_answer = ""
        for delta in llm.stream_answer(question, context, conversation_history):
            full_answer += delta
            yield {"type": "delta", "text": delta}
    generation_ms = (time.perf_counter() - gen_start) * 1000

    is_no_info = settings.NO_INFO_MESSAGE.strip() in full_answer
    suggestions = _suggest_clarifications(question, dependencia_id=dependencia_id) if is_no_info else []

    if cached_answer is None:
        # Se cachea el texto crudo (con la línea FUENTES_USADAS) antes de
        # separarla, para que una respuesta repetida servida desde caché
        # también se pueda filtrar la próxima vez.
        answer_cache_service.maybe_store_answer(retrieval_question, chunks, full_answer)

    full_answer, used_sources = llm.extract_used_sources(full_answer)
    relevant_chunks = _filter_chunks_by_used_sources(chunks, used_sources)
    sources = [] if is_no_info else _dedup_sources(relevant_chunks)

    turn_created_at = _save_and_broadcast_turn(
        session_id,
        question,
        full_answer,
        sources=None if is_no_info else sources,
        suggestions=suggestions,
        dependencia_id=dependencia_id,
    )

    history_service.record_chat_metrics(
        session_id,
        round(retrieval_ms, 2),
        round(generation_ms, 2),
        round(retrieval_ms + generation_ms, 2),
        len(chunks),
        cache_hit=cached_answer is not None,
    )

    yield {
        "type": "done",
        # Fuentes ya filtradas por lo que el LLM reportó haber usado de
        # verdad (ver llm.extract_used_sources) -- las del evento "meta"
        # de más arriba se mandaron ANTES de generar la respuesta, con
        # todo lo que pasó el re-ranking; el frontend debe preferir esta
        # lista para la sección "Archivos consultados" que se muestra al
        # final.
        "sources": [s.model_dump() for s in sources],
        "suggestions": suggestions,
        "turn_created_at": turn_created_at,
        "metrics": {
            "retrieval_ms": round(retrieval_ms, 2),
            "generation_ms": round(generation_ms, 2),
            "total_ms": round(retrieval_ms + generation_ms, 2),
            "chunks_retrieved": len(chunks),
        },
    }
