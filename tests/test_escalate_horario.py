"""Pruebas de app/api/routes.py::escalate -- el chequeo de horario de
atención (within_horario/horario_texto) y el teléfono opcional de
contacto alterno (ver app/services/admin_service.py::is_within_horario)."""
import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service
from app.services import history as history_service

client = TestClient(app)

_counter = 0


def _login_as(role="root", password="clave-segura-123"):
    global _counter
    _counter += 1
    username = f"test-esc-horario-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _escalate(session_id, dependencia_id, phone=None):
    history_service.append_turn(session_id, "pregunta", "respuesta")
    payload = {"session_id": session_id, "name": "Estudiante", "email": "e@test.com"}
    if phone is not None:
        payload["phone"] = phone
    with (
        patch("app.rag.llm.classify_department", return_value=dependencia_id),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        return client.post("/api/escalate", json=payload)


def test_escalate_without_dependencia_is_always_within_horario():
    res = _escalate("esc-horario-sin-dep", None)

    assert res.status_code == 200
    assert res.json()["within_horario"] is True
    assert "horario_texto" not in res.json()


def test_escalate_within_configured_horario():
    root_token = _login_as()
    dep_id = client.post(
        "/api/root/dependencias", json={"name": "Dep Esc Horario A", "description": "d"}, headers=_auth(root_token)
    ).json()["id"]
    today = datetime.datetime.now().isoweekday()
    client.put(
        f"/api/root/dependencias/{dep_id}/horario",
        json={"dias": [today], "rangos": [{"inicio": "00:00", "fin": "23:59"}]},
        headers=_auth(root_token),
    )

    res = _escalate("esc-horario-dentro", dep_id)

    assert res.json()["within_horario"] is True
    assert "horario_texto" not in res.json()


def test_escalate_outside_configured_horario_includes_horario_texto():
    root_token = _login_as()
    dep_id = client.post(
        "/api/root/dependencias", json={"name": "Dep Esc Horario B", "description": "d"}, headers=_auth(root_token)
    ).json()["id"]
    today = datetime.datetime.now().isoweekday()
    other_day = 1 if today != 1 else 2
    client.put(
        f"/api/root/dependencias/{dep_id}/horario",
        json={"dias": [other_day], "rangos": [{"inicio": "00:00", "fin": "23:59"}]},
        headers=_auth(root_token),
    )

    res = _escalate("esc-horario-fuera", dep_id)

    assert res.json()["within_horario"] is False
    assert res.json()["horario_texto"]


def test_escalate_saves_optional_phone():
    session_id = "esc-horario-con-telefono"
    _escalate(session_id, None, phone="3001234567")

    # get_session_meta no expone student_phone hoy -- se verifica a través
    # de list_sessions, que sí lo trae completo para el panel.
    sessions = history_service.list_sessions(dependencia_scope=None)["sessions"]
    match = next((s for s in sessions if s["session_id"] == session_id), None)
    assert match is not None
    assert match["student_phone"] == "3001234567"
