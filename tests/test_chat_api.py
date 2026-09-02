"""Pruebas de la API HTTP (FastAPI TestClient).

Las llamadas reales a Groq se simulan (mock) para que los tests corran offline
y sin necesitar una API key válida.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import ChatMetrics, ChatResponse, SourceCitation

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "documents_indexed" in body


def test_chat_without_api_key_returns_503(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    response = client.post("/api/chat", json={"session_id": "s1", "message": "hola"})

    assert response.status_code == 503


def test_chat_rejects_empty_message():
    response = client.post("/api/chat", json={"session_id": "s1", "message": ""})

    assert response.status_code == 422


@patch("app.api.routes.chat_service.answer_question")
def test_chat_returns_answer_with_sources(mock_answer):
    mock_answer.return_value = ChatResponse(
        answer="Debes aprobar el 100% de los créditos.",
        sources=[
            SourceCitation(document="Reglamento.pdf", page=20, chunk_id="a1", similarity=0.9)
        ],
        has_sufficient_info=True,
        metrics=ChatMetrics(retrieval_ms=5.0, generation_ms=300.0, total_ms=305.0, chunks_retrieved=1),
    )

    response = client.post(
        "/api/chat", json={"session_id": "s1", "message": "¿Requisitos de grado?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_sufficient_info"] is True
    assert body["sources"][0]["document"] == "Reglamento.pdf"


@patch("app.api.routes.chat_service.answer_question")
def test_chat_reports_insufficient_info(mock_answer):
    mock_answer.return_value = ChatResponse(
        answer=settings.NO_INFO_MESSAGE,
        sources=[],
        has_sufficient_info=False,
        metrics=ChatMetrics(retrieval_ms=5.0, generation_ms=0.0, total_ms=5.0, chunks_retrieved=0),
    )

    response = client.post(
        "/api/chat", json={"session_id": "s1", "message": "¿Cuál es el clima hoy?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_sufficient_info"] is False
    assert body["sources"] == []
