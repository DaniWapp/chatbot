"""Pruebas del pipeline de chat_service.

Los saludos, agradecimientos y charla casual ya NO se detectan con
expresiones regulares propias: todo mensaje pasa por el LLM (con contexto de
documentos si se encontró alguno relevante, o vacío si no), y es el propio
modelo quien decide el tono de la respuesta según las instrucciones de
app/rag/llm.py. Estas pruebas verifican que el pipeline llama al LLM en
ambos casos y que "has_sufficient_info"/"sources" se derivan correctamente
del contenido de la respuesta generada (mockeada, sin llamar a Groq real).
"""
from unittest.mock import MagicMock, patch

from app.config import settings
from app.rag import llm
from app.rag.retriever import RetrievedChunk
from app.services import chat_service


def _fake_client_returning(json_content):
    fake_client = MagicMock()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json_content))]
    fake_client.chat.completions.create.return_value = completion
    return fake_client


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_llm_is_called_even_without_retrieved_chunks(mock_retrieve, mock_generate):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = (
        "¡Hola! Soy el asistente virtual de la Facultad de Ingeniería. "
        "¿En qué puedo ayudarte?"
    )

    response = chat_service.answer_question("s1", "hola")

    mock_generate.assert_called_once()
    assert response.has_sufficient_info is True
    assert response.sources == []


@patch("app.services.chat_service.retrieve_below_threshold")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_info_message_marks_insufficient_info(mock_retrieve, mock_generate, mock_retrieve_weak):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE
    mock_retrieve_weak.return_value = []

    response = chat_service.answer_question("s1", "¿cuál es el clima hoy?")

    assert response.has_sufficient_info is False
    assert response.sources == []
    assert response.suggestions == []


@patch("app.services.chat_service.llm.suggest_clarifying_questions")
@patch("app.services.chat_service.retrieve_below_threshold")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_info_response_includes_suggestions_when_weak_candidates_exist(
    mock_retrieve, mock_generate, mock_retrieve_weak, mock_suggest
):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE
    mock_retrieve_weak.return_value = [
        RetrievedChunk(chunk_id="c1", text="texto", document="doc.txt", page=1, similarity=0.3)
    ]
    mock_suggest.return_value = ["¿Tienen ingeniería en TIC?"]

    response = chat_service.answer_question("s1", "ing tic")

    assert response.suggestions == ["¿Tienen ingeniería en TIC?"]
    mock_suggest.assert_called_once()


@patch("app.services.chat_service.retrieve_below_threshold")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_suggestions_when_no_weak_candidates(mock_retrieve, mock_generate, mock_retrieve_weak):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE
    mock_retrieve_weak.return_value = []

    response = chat_service.answer_question("s1", "¿cuánto es 2+2?")

    assert response.suggestions == []


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_answer_with_chunks_includes_sources(mock_retrieve, mock_generate):
    chunk = RetrievedChunk(
        chunk_id="c1", text="Texto del reglamento...", document="Reglamento.pdf", page=5, similarity=0.8
    )
    mock_retrieve.return_value = ([chunk], 5.0)
    mock_generate.return_value = "Según el Reglamento Estudiantil, debes cumplir X."

    response = chat_service.answer_question("s1", "¿requisitos de grado?")

    assert response.has_sufficient_info is True
    assert len(response.sources) == 1
    assert response.sources[0].document == "Reglamento.pdf"


# --- llm.suggest_clarifying_questions (unidad, Groq simulado) -----------


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_returns_parsed_list(mock_get_client):
    mock_get_client.return_value = _fake_client_returning(
        '{"suggestions": ["¿Tienen ingeniería en TIC?", "¿Cuánto dura la carrera?"]}'
    )
    candidate = RetrievedChunk(chunk_id="c1", text="texto sobre TIC", document="faq.txt", page=1, similarity=0.3)

    result = llm.suggest_clarifying_questions("ing tic", [candidate])

    assert result == ["¿Tienen ingeniería en TIC?", "¿Cuánto dura la carrera?"]


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_handles_empty_list_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"suggestions": []}')
    candidate = RetrievedChunk(chunk_id="c1", text="texto no relacionado", document="doc.txt", page=1, similarity=0.26)

    assert llm.suggest_clarifying_questions("asdf", [candidate]) == []


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_handles_malformed_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("esto no es json")
    candidate = RetrievedChunk(chunk_id="c1", text="texto", document="doc.txt", page=1, similarity=0.3)

    assert llm.suggest_clarifying_questions("pregunta", [candidate]) == []


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_handles_client_exception(mock_get_client):
    mock_get_client.side_effect = RuntimeError("groq caído")
    candidate = RetrievedChunk(chunk_id="c1", text="texto", document="doc.txt", page=1, similarity=0.3)

    assert llm.suggest_clarifying_questions("pregunta", [candidate]) == []


def test_suggest_clarifying_questions_returns_empty_without_candidates():
    assert llm.suggest_clarifying_questions("pregunta", []) == []
