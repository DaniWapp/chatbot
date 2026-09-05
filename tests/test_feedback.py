"""Pruebas del feedback 👍/👎 por respuesta (app/services/history.py::
record_feedback/get_feedback_summary, POST /api/sessions/{id}/feedback)."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import history as history_service

client = TestClient(app)


def test_record_feedback_and_change_vote():
    unique = uuid.uuid4().hex
    session_id = f"s-feedback-{unique}"
    turn_created_at = f"2026-01-01T00:00:00+00:00-{unique}"

    history_service.record_feedback(session_id, turn_created_at, "up")
    history_service.record_feedback(session_id, turn_created_at, "down")  # cambia de opinión

    with history_service.db_lock():
        conn = history_service.get_connection()
        rows = conn.execute(
            "SELECT rating FROM answer_feedback WHERE session_id = ? AND turn_created_at = ?",
            (session_id, turn_created_at),
        ).fetchall()

    assert rows == [("down",)]  # una sola fila, con el voto más reciente


def test_feedback_endpoint_persists_vote():
    unique = uuid.uuid4().hex
    session_id = f"s-feedback-api-{unique}"
    turn_created_at = f"2026-01-01T00:00:00+00:00-{unique}"

    res = client.post(f"/api/sessions/{session_id}/feedback", json={"turn_created_at": turn_created_at, "rating": "up"})

    assert res.status_code == 200
    with history_service.db_lock():
        conn = history_service.get_connection()
        row = conn.execute(
            "SELECT rating FROM answer_feedback WHERE session_id = ? AND turn_created_at = ?",
            (session_id, turn_created_at),
        ).fetchone()
    assert row == ("up",)


def test_feedback_endpoint_rejects_invalid_rating():
    res = client.post("/api/sessions/s1/feedback", json={"turn_created_at": "2026-01-01T00:00:00+00:00", "rating": "meh"})

    assert res.status_code == 422


def test_feedback_summary_counts_and_lists_most_disliked():
    unique = uuid.uuid4().hex
    session_id = f"s-summary-{unique}"
    question = f"¿Cuál es el proceso para {unique}?"

    history_service.append_turn(session_id, question, "Una respuesta poco útil.")
    turn = history_service.get_history_page(session_id, limit=1)["messages"]
    turn_created_at = next(m["created_at"] for m in turn if m["sender"] == "assistant")

    history_service.record_feedback(f"{session_id}-a", turn_created_at, "down")
    history_service.record_feedback(session_id, turn_created_at, "down")
    history_service.record_feedback(f"{session_id}-b", f"otro-turno-{unique}", "up")

    summary = history_service.get_feedback_summary()

    assert summary["down"] >= 2
    assert summary["up"] >= 1
    disliked_questions = [row["question"] for row in summary["most_disliked"]]
    assert question in disliked_questions


def test_chat_response_and_stream_expose_turn_created_at(monkeypatch):
    from unittest.mock import patch

    from app.services import chat_service

    unique = uuid.uuid4().hex

    with patch("app.services.chat_service.retrieve_context", return_value=([], 1.0)), patch(
        "app.rag.llm.generate_answer", return_value=f"Respuesta {unique}"
    ):
        response = chat_service.answer_question(f"s-turnid-{unique}", "hola")
    assert response.turn_created_at is not None

    with patch("app.services.chat_service.retrieve_context", return_value=([], 1.0)), patch(
        "app.rag.llm.stream_answer", return_value=iter([f"Respuesta {unique}"])
    ):
        events = list(chat_service.stream_answer(f"s-turnid-stream-{unique}", "hola"))
    done_event = next(e for e in events if e["type"] == "done")
    assert done_event["turn_created_at"] is not None
