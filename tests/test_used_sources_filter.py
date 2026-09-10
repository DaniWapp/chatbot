"""Pruebas del filtrado de "Archivos consultados" por lo que el LLM
reportó haber usado de verdad (app/rag/llm.py::extract_used_sources,
app/services/chat_service.py::_filter_chunks_by_used_sources). No
dependen de Groq, la red, ni del modelo real de re-ranking -- todo se
mockea."""
import uuid
from unittest.mock import patch

from app.rag import llm
from app.rag.retriever import RetrievedChunk
from app.services import chat_service


def _chunk(chunk_id: str, document: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, text=text, document=document, page=1, similarity=0.9)


# --- Unidad: llm.extract_used_sources --------------------------------------


def test_extract_used_sources_parses_the_marker_line():
    raw = "La respuesta real.\nFUENTES_USADAS: Reglamento.txt, Calendario.pdf"
    clean_text, names = llm.extract_used_sources(raw)
    assert clean_text == "La respuesta real."
    assert names == ["Reglamento.txt", "Calendario.pdf"]


def test_extract_used_sources_returns_none_when_marker_absent():
    raw = "Una respuesta que nunca mencionó la línea especial."
    clean_text, names = llm.extract_used_sources(raw)
    assert clean_text == raw
    assert names is None


def test_extract_used_sources_handles_single_source():
    raw = "Respuesta.\nFUENTES_USADAS: Solo_un_archivo.txt"
    clean_text, names = llm.extract_used_sources(raw)
    assert clean_text == "Respuesta."
    assert names == ["Solo_un_archivo.txt"]


# --- Unidad: chat_service._filter_chunks_by_used_sources --------------------


def test_filter_keeps_only_chunks_from_used_documents():
    real = _chunk("a", "Reglamento.txt", "texto real")
    noise = _chunk("b", "Matriz_Bibliografica.xlsx", "ruido sin relación")
    filtered = chat_service._filter_chunks_by_used_sources([real, noise], ["Reglamento.txt"])
    assert filtered == [real]


def test_filter_falls_back_to_all_chunks_when_no_names_reported():
    real = _chunk("a", "Reglamento.txt", "texto real")
    noise = _chunk("b", "Matriz_Bibliografica.xlsx", "ruido sin relación")
    assert chat_service._filter_chunks_by_used_sources([real, noise], None) == [real, noise]


def test_filter_falls_back_to_all_chunks_when_reported_names_match_nothing():
    """El LLM pudo escribir el nombre distinto (typo, truncado) -- nunca
    debe dejar la lista de fuentes vacía por eso, se prefiere mostrar de
    más a mostrar nada."""
    real = _chunk("a", "Reglamento.txt", "texto real")
    assert chat_service._filter_chunks_by_used_sources([real], ["Nombre_Que_No_Coincide.txt"]) == [real]


# --- Integración: chat_service.answer_question ------------------------------


def _rerank_passthrough(question, chunks, top_k, min_score):
    return chunks[:top_k]


@patch("app.services.chat_service.reranker.rerank", side_effect=_rerank_passthrough)
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_answer_only_cites_documents_the_llm_reported_using(mock_retrieve, mock_generate, mock_rerank):
    unique = uuid.uuid4().hex
    session_id = f"s-usedsources-{unique}"

    real_chunk = _chunk(f"real-{unique}", "Reglamento_Estudiantil_EJEMPLO.txt", f"Requisito real ({unique}).")
    noise_chunk = _chunk(f"noise-{unique}", "Matriz_Bibliografica.xlsx", f"Cita sin relación ({unique}).")
    mock_retrieve.return_value = ([real_chunk, noise_chunk], 1.0)
    mock_generate.return_value = (
        f"El requisito es X ({unique}).\n"
        "FUENTES_USADAS: Reglamento_Estudiantil_EJEMPLO.txt"
    )

    response = chat_service.answer_question(session_id, "una pregunta cualquiera")

    # La línea FUENTES_USADAS no debe llegar al estudiante.
    assert "FUENTES_USADAS" not in response.answer
    assert f"El requisito es X ({unique})." == response.answer
    # Solo el documento real reportado por el LLM aparece como fuente.
    assert len(response.sources) == 1
    assert response.sources[0].document == "Reglamento_Estudiantil_EJEMPLO.txt"


@patch("app.services.chat_service.reranker.rerank", side_effect=_rerank_passthrough)
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_answer_without_marker_still_shows_all_sources_as_before(mock_retrieve, mock_generate, mock_rerank):
    """Compatibilidad hacia atrás: si el LLM no incluye la línea (formato
    inesperado, o una respuesta cacheada de antes de este cambio), se
    sigue mostrando todo lo recuperado -- nunca peor que antes."""
    unique = uuid.uuid4().hex
    session_id = f"s-nomark-{unique}"

    chunk_a = _chunk(f"a-{unique}", "Doc_A.txt", f"Texto A ({unique}).")
    chunk_b = _chunk(f"b-{unique}", "Doc_B.txt", f"Texto B ({unique}).")
    mock_retrieve.return_value = ([chunk_a, chunk_b], 1.0)
    mock_generate.return_value = f"Respuesta sin la línea especial ({unique})."

    response = chat_service.answer_question(session_id, "otra pregunta")

    assert len(response.sources) == 2
