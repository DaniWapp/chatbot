"""Pruebas de la fase 5: el administrador general como supervisor de todo
el sistema (lectura sin restricción, pero debe reclamar una conversación
antes de poder responderla) y el auto-escalamiento por SLA vencido (5
minutos sin respuesta del asesor asignado)."""
import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.routes import _perform_reassignment
from app.main import app
from app.services import admin_service
from app.services import history as history_service

client = TestClient(app)

_counter = 0


def _login_as(role="general", dependencia_id=None, password="clave-segura-123"):
    global _counter
    _counter += 1
    username = f"test-oversight-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_dependencia(root_token, name):
    return client.post(
        "/api/root/dependencias", json={"name": name, "description": "desc"}, headers=_auth(root_token)
    ).json()


def _escalate(session_id, dependencia_id):
    history_service.append_turn(session_id, "pregunta", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=dependencia_id),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        return client.post(
            "/api/escalate", json={"session_id": session_id, "name": "Estudiante", "email": "e@test.com"}
        )


def _backdate_assignment(session_id, minutes_ago):
    backdated = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)).isoformat()
    with history_service.db_lock():
        conn = history_service.get_connection()
        conn.execute(
            "UPDATE session_meta SET dependencia_assigned_at = ? WHERE session_id = ?", (backdated, session_id)
        )
        conn.commit()


# --- El general ve todo, pero debe reclamar antes de poder actuar --------


def test_general_can_view_but_not_act_on_dependencia_session():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep Oversight A")
    sid = "oversight-view-act"
    _escalate(sid, dep["id"])

    token_general = _login_as(role="general")

    # Lectura: permitida sin reclamarla.
    read_res = client.get(f"/api/admin/sessions/{sid}/messages", headers=_auth(token_general))
    assert read_res.status_code == 200

    # Acción: bloqueada hasta que la reclame.
    reply_res = client.post(
        f"/api/admin/sessions/{sid}/reply", json={"message": "hola"}, headers=_auth(token_general)
    )
    assert reply_res.status_code == 403

    # La reclama (se redirige hacia sí mismo).
    claim_res = client.post(
        f"/api/admin/sessions/{sid}/reassign", json={"dependencia_id": None}, headers=_auth(token_general)
    )
    assert claim_res.status_code == 200

    # Ahora sí puede responder.
    reply_after_res = client.post(
        f"/api/admin/sessions/{sid}/reply", json={"message": "hola, ya te atiendo"}, headers=_auth(token_general)
    )
    assert reply_after_res.status_code == 200


def test_general_sees_all_escalated_sessions_regardless_of_dependencia():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep Oversight B")
    sid = "oversight-see-all"
    _escalate(sid, dep["id"])

    token_general = _login_as(role="general")
    sessions = client.get("/api/admin/sessions", headers=_auth(token_general)).json()["sessions"]

    session_entry = next((s for s in sessions if s["session_id"] == sid), None)
    assert session_entry is not None
    assert session_entry["dependencia_id"] == dep["id"]


def test_dependencia_admin_loses_access_once_general_claims_it():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep Oversight C")
    sid = "oversight-claim-removes-access"
    _escalate(sid, dep["id"])

    token_dep = _login_as(role="dependencia", dependencia_id=dep["id"])
    token_general = _login_as(role="general")
    client.post(f"/api/admin/sessions/{sid}/reassign", json={"dependencia_id": None}, headers=_auth(token_general))

    res = client.get(f"/api/admin/sessions/{sid}/messages", headers=_auth(token_dep))
    assert res.status_code == 403


# --- Auto-escalamiento por SLA vencido -----------------------------------


def test_find_unattended_sessions_detects_overdue_assignment():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep SLA A")
    sid = "sla-overdue"
    _escalate(sid, dep["id"])
    _backdate_assignment(sid, minutes_ago=10)

    overdue = history_service.find_unattended_sessions(timeout_seconds=300)

    assert any(item["session_id"] == sid and item["dependencia_id"] == dep["id"] for item in overdue)


def test_find_unattended_sessions_ignores_recent_assignment():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep SLA B")
    sid = "sla-recent"
    _escalate(sid, dep["id"])  # dependencia_assigned_at = ahora mismo

    overdue = history_service.find_unattended_sessions(timeout_seconds=300)

    assert not any(item["session_id"] == sid for item in overdue)


def test_advisor_response_marks_first_response_and_prevents_auto_escalation():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep SLA C")
    sid = "sla-already-attended"
    _escalate(sid, dep["id"])
    _backdate_assignment(sid, minutes_ago=10)

    token_dep = _login_as(role="dependencia", dependencia_id=dep["id"])
    reply_res = client.post(f"/api/admin/sessions/{sid}/reply", json={"message": "ya te ayudo"}, headers=_auth(token_dep))
    assert reply_res.status_code == 200

    overdue = history_service.find_unattended_sessions(timeout_seconds=300)
    assert not any(item["session_id"] == sid for item in overdue)


def test_perform_reassignment_moves_session_and_resets_clock():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep SLA D")
    sid = "sla-auto-reassign"
    _escalate(sid, dep["id"])
    _backdate_assignment(sid, minutes_ago=10)

    _perform_reassignment(sid, None, dep["id"])

    meta = history_service.get_session_meta(sid)
    assert meta["dependencia_id"] is None
    # el reloj se reinicio: ya no deberia aparecer como vencido inmediatamente despues
    overdue = history_service.find_unattended_sessions(timeout_seconds=300)
    assert not any(item["session_id"] == sid for item in overdue)
