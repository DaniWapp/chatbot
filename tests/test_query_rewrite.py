"""Pruebas de la reformulación de preguntas de seguimiento antes de buscar
(app/services/chat_service.py::_needs_query_rewrite,
app/rag/llm.py::rewrite_query_variations). No dependen de Groq, la red, ni
del modelo real de re-ranking -- todo se mockea."""
import uuid
from unittest.mock import patch

from app.rag.retriever import RetrievedChunk
from app.services import chat_service, history as history_service


def _chunk(chunk_id: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, text=text, document="doc.txt", page=1, similarity=0.9)


# --- Unidad: _needs_query_rewrite -----------------------------------------


def test_needs_rewrite_when_no_chunks_and_history_exists():
    assert chat_service._needs_query_rewrite([], [("pregunta previa", "respuesta previa")]) is True


def test_no_rewrite_without_history_even_with_empty_chunks():
    assert chat_service._needs_query_rewrite([], []) is False


def test_no_rewrite_when_chunks_were_found():
    chunk = _chunk("a", "texto")
    assert chat_service._needs_query_rewrite([chunk], [("pregunta previa", "respuesta previa")]) is False
    assert chat_service._needs_query_rewrite([chunk], []) is False


# --- Integración: chat_service.answer_question ----------------------------


def _rerank_passthrough(question, chunks, top_k, min_score):
    return chunks[:top_k]


@patch("app.services.chat_service.reranker.rerank", side_effect=_rerank_passthrough)
@patch("app.rag.llm.rewrite_query_variations")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_followup_question_retries_with_rewritten_query(mock_retrieve, mock_generate, mock_rewrite, mock_rerank):
    unique = uuid.uuid4().hex
    session_id = f"s-rewrite-{unique}"
    history_service.append_turn(session_id, "¿Existe la carrera de Ingeniería en TIC?", "Sí, existe.")

    real_chunk = _chunk(f"tic-{unique}", f"El precio de Ingeniería en TIC es X ({unique}).")
    mock_retrieve.side_effect = [([], 1.0), ([real_chunk], 2.0)]  # vacío con "precio", encuentra con la reescritura
    mock_rewrite.return_value = ["precio de Ingeniería en TIC"]
    mock_generate.return_value = f"El precio es X ({unique})."

    response = chat_service.answer_question(session_id, "precio")

    assert mock_retrieve.call_count == 2
    mock_rewrite.assert_called_once()
    assert real_chunk.text in mock_generate.call_args.args[1]  # el context que llegó al LLM
    assert response.has_sufficient_info is True
    assert len(response.sources) == 1
    assert response.sources[0].document == "doc.txt"


@patch("app.services.chat_service.reranker.rerank", side_effect=_rerank_passthrough)
@patch("app.rag.llm.rewrite_query_variations")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_multiple_variations_combine_without_duplicates(mock_retrieve, mock_generate, mock_rewrite, mock_rerank):
    unique = uuid.uuid4().hex
    session_id = f"s-multiquery-{unique}"
    history_service.append_turn(session_id, "¿Existe la carrera de Ingeniería en TIC?", "Sí, existe.")

    shared_chunk = _chunk(f"shared-{unique}", f"Fragmento compartido ({unique}).")
    only_v1_chunk = _chunk(f"v1-{unique}", f"Solo lo encuentra la variación 1 ({unique}).")
    only_v2_chunk = _chunk(f"v2-{unique}", f"Solo lo encuentra la variación 2 ({unique}).")
    mock_retrieve.side_effect = [
        ([], 1.0),  # pregunta original: nada
        ([shared_chunk, only_v1_chunk], 1.0),  # variación 1
        ([shared_chunk, only_v2_chunk], 1.0),  # variación 2 (repite shared_chunk)
    ]
    mock_rewrite.return_value = ["variación uno de la pregunta", "variación dos de la pregunta"]
    mock_generate.return_value = f"Respuesta combinada ({unique})."

    chat_service.answer_question(session_id, "precio")

    assert mock_retrieve.call_count == 3  # original + 2 variaciones
    context_sent = mock_generate.call_args.args[1]
    assert shared_chunk.text in context_sent
    assert only_v1_chunk.text in context_sent
    assert only_v2_chunk.text in context_sent
    assert context_sent.count(shared_chunk.text) == 1  # no duplicado a pesar de aparecer en ambas variaciones


@patch("app.services.chat_service.reranker.rerank", side_effect=_rerank_passthrough)
@patch("app.rag.llm.rewrite_query_variations")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_rewrite_failure_falls_back_to_no_info(mock_retrieve, mock_generate, mock_rewrite, mock_rerank):
    from app.config import settings

    unique = uuid.uuid4().hex
    session_id = f"s-rewrite-fail-{unique}"
    history_service.append_turn(session_id, "¿Existe la carrera de Ingeniería en TIC?", "Sí, existe.")

    mock_retrieve.return_value = ([], 1.0)  # nunca encuentra nada, ni con la pregunta ni con las reescrituras
    mock_rewrite.return_value = []  # Groq falló al reformular (o no devolvió nada usable)
    mock_generate.return_value = settings.NO_INFO_MESSAGE

    response = chat_service.answer_question(session_id, "precio")

    mock_rewrite.assert_called_once()
    assert mock_retrieve.call_count == 1  # no reintenta la búsqueda sin variaciones válidas
    assert response.has_sufficient_info is False


@patch("app.rag.llm.rewrite_query_variations")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_history_never_triggers_rewrite(mock_retrieve, mock_generate, mock_rewrite):
    unique = uuid.uuid4().hex
    session_id = f"s-rewrite-nohistory-{unique}"  # sesión nueva, sin turnos previos

    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = f"¡Hola! ¿En qué te ayudo? ({unique})"

    chat_service.answer_question(session_id, "hola")

    mock_rewrite.assert_not_called()
    assert mock_retrieve.call_count == 1


@patch("app.rag.llm.rewrite_query_variations")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_successful_first_try_never_triggers_rewrite(mock_retrieve, mock_generate, mock_rewrite):
    unique = uuid.uuid4().hex
    session_id = f"s-rewrite-happy-{unique}"
    history_service.append_turn(session_id, "pregunta previa", "respuesta previa")

    chunk = _chunk(f"happy-{unique}", f"Texto encontrado a la primera ({unique}).")
    mock_retrieve.return_value = ([chunk], 1.0)
    mock_generate.return_value = f"Respuesta ({unique})."

    chat_service.answer_question(session_id, "una pregunta bastante completa y clara")

    mock_rewrite.assert_not_called()
    assert mock_retrieve.call_count == 1
