"""Pruebas de la sección "preguntas sin respuesta suficiente" del
Dashboard (app/services/dashboard_service.py::_unanswered_questions_section).
Las demás secciones del dashboard ya se verificaron manualmente al
construirlas; esta cubre la pieza nueva."""
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import admin_service, dashboard_service, history as history_service

client = TestClient(app)


def _login_as(role="root", dependencia_id=None, password="clave-segura-123"):
    username = f"test-dashboard-{role}-{uuid.uuid4().hex}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_unanswered_questions_groups_and_counts_by_question():
    unique = uuid.uuid4().hex
    question = f"¿Cuánto cuesta el programa fantasma {unique}?"
    session_id = f"s-unanswered-{unique}"

    history_service.append_turn(session_id, question, settings.NO_INFO_MESSAGE)
    history_service.append_turn(session_id, question, settings.NO_INFO_MESSAGE)
    history_service.append_turn(session_id, f"otra pregunta distinta {unique}", "Una respuesta real, con información.")

    dashboard = dashboard_service.get_dashboard(None, include_admin_and_performance=True)
    top = dashboard["unanswered_questions"]["top"]
    entry = next((row for row in top if row["question"] == question), None)

    assert entry is not None
    assert entry["count"] == 2
    assert all(row["question"] != f"otra pregunta distinta {unique}" for row in top)


def test_unanswered_questions_only_for_root():
    general_token = _login_as(role="general")
    res = client.get("/api/dashboard", headers=_auth(general_token))

    assert res.status_code == 200
    assert res.json()["unanswered_questions"] is None


def test_unanswered_questions_present_for_root():
    root_token = _login_as(role="root")
    res = client.get("/api/dashboard", headers=_auth(root_token))

    assert res.status_code == 200
    assert res.json()["unanswered_questions"] is not None
