"""Pruebas del pipeline de chat_service.

Los saludos, agradecimientos y charla casual ya NO se detectan con
expresiones regulares propias: todo mensaje pasa por el LLM (con contexto de
documentos si se encontró alguno relevante, o vacío si no), y es el propio
modelo quien decide el tono de la respuesta según las instrucciones de
app/rag/llm.py. Estas pruebas verifican que el pipeline llama al LLM en
ambos casos y que "has_sufficient_info"/"sources" se derivan correctamente
del contenido de la respuesta generada (mockeada, sin llamar a Groq real).
"""
from unittest.mock import patch

from app.config import settings
from app.rag.retriever import RetrievedChunk
from app.services import chat_service


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


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_info_message_marks_insufficient_info(mock_retrieve, mock_generate):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE

    response = chat_service.answer_question("s1", "¿cuál es el clima hoy?")

    assert response.has_sufficient_info is False
    assert response.sources == []


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
