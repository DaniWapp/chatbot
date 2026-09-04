"""Pruebas HTTP del panel de control: autenticación con cuentas reales de
administrador (login/logout, roles), paginación de la lista de sesiones y
de los mensajes de una conversación, y el flujo completo (vía API) de "¿Te
puedo ayudar con algo más?".

Los turnos de conversación se siembran directamente con history_service
(no vía /api/chat) para no depender de una llamada real a Groq -- igual
que el resto de tests, /api/chat solo se ejercita con
chat_service.answer_question mockeado."""
from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service
from app.services import history as history_service

client = TestClient(app)

_counter = 0


def _login_as(role="general", dependencia_id=None):
    """Crea una cuenta de administrador nueva (usuario único por llamada) y
    devuelve el token de sesión ya logueado."""
    global _counter
    _counter += 1
    username = f"test-admin-{role}-{_counter}"
    admin_service.create_admin(username, "clave-segura-123", f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": "clave-segura-123"})
    assert res.status_code == 200
    return res.json()["token"]


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_rejects_wrong_password():
    username = "test-login-wrongpass"
    admin_service.create_admin(username, "clave-correcta", "Admin", "general")

    response = client.post("/api/auth/login", json={"username": username, "password": "clave-incorrecta"})

    assert response.status_code == 401


def test_login_rejects_unknown_username():
    response = client.post("/api/auth/login", json={"username": "no-existe", "password": "lo-que-sea"})

    assert response.status_code == 401


def test_logout_invalidates_the_token():
    token = _login_as()
    assert client.get("/api/admin/sessions", headers=_auth_headers(token)).status_code == 200

    logout_res = client.post("/api/auth/logout", headers=_auth_headers(token))
    assert logout_res.status_code == 200

    assert client.get("/api/admin/sessions", headers=_auth_headers(token)).status_code == 401


def test_admin_sessions_requires_token():
    response = client.get("/api/admin/sessions")

    assert response.status_code == 401


def test_admin_sessions_rejects_wrong_token():
    response = client.get("/api/admin/sessions", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401


def test_root_cannot_access_conversations():
    """El root no administra conversaciones -- confirmado con el usuario."""
    token = _login_as(role="root")

    response = client.get("/api/admin/sessions", headers=_auth_headers(token))

    assert response.status_code == 403


def test_admin_sessions_pagination_shape():
    token = _login_as()
    for i in range(3):
        sid = f"api-pag-{i}"
        history_service.append_turn(sid, "hola", "respuesta")
        history_service.escalate_session(sid, "Estudiante", f"api-pag-{i}@test.com")

    response = client.get("/api/admin/sessions?offset=0&limit=2", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"sessions", "total", "has_more", "pending_count"}
    assert len(body["sessions"]) == 2
    assert body["total"] >= 3


def test_session_history_pagination_shape_and_no_admin_token_required():
    sid = "api-history-shape"
    for i in range(3):
        history_service.append_turn(sid, f"pregunta {i}", f"respuesta {i}")

    response = client.get(f"/api/sessions/{sid}/history?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"messages", "has_more", "next_cursor"}
    assert len(body["messages"]) == 2
    assert body["has_more"] is True
    assert body["next_cursor"]


def test_checkin_flow_end_to_end_through_api():
    token = _login_as()
    sid = "api-checkin-flow"
    history_service.append_turn(sid, "hola", "respuesta")

    escalate_res = client.post(
        "/api/escalate", json={"session_id": sid, "name": "Estudiante API", "email": "api@test.com"}
    )
    assert escalate_res.status_code == 200

    ask_res = client.post(f"/api/admin/sessions/{sid}/ask-continue", headers=_auth_headers(token))
    assert ask_res.status_code == 200

    status_before = client.get(f"/api/session-status/{sid}")
    assert status_before.json()["needs_human"] is True

    no_res = client.post(f"/api/sessions/{sid}/checkin-response", json={"wants_more_help": False})
    assert no_res.status_code == 200
    assert no_res.json()["resolved_at"] is not None

    status_after = client.get(f"/api/session-status/{sid}")
    assert status_after.json()["needs_human"] is False


def test_checkin_flow_yes_keeps_session_escalated():
    token = _login_as()
    sid = "api-checkin-flow-yes"
    history_service.append_turn(sid, "hola", "respuesta")

    client.post("/api/escalate", json={"session_id": sid, "name": "Estudiante API", "email": "api2@test.com"})
    client.post(f"/api/admin/sessions/{sid}/ask-continue", headers=_auth_headers(token))

    yes_res = client.post(f"/api/sessions/{sid}/checkin-response", json={"wants_more_help": True})
    assert yes_res.status_code == 200
    assert yes_res.json()["resolved_at"] is None

    status_after = client.get(f"/api/session-status/{sid}")
    assert status_after.json()["needs_human"] is True


def test_ask_continue_requires_admin_session():
    sid = "api-checkin-no-auth"
    history_service.append_turn(sid, "hola", "respuesta")

    response = client.post(f"/api/admin/sessions/{sid}/ask-continue")

    assert response.status_code == 401


def test_ask_bot_requires_admin_session():
    sid = "api-ask-bot-no-auth"
    history_service.append_turn(sid, "hola", "respuesta")

    response = client.post(f"/api/admin/sessions/{sid}/ask-bot", json={"question": "pregunta"})

    assert response.status_code == 401


def test_ask_bot_rejects_admin_without_access_to_session():
    from unittest.mock import patch

    root_token = _login_as(role="root")
    dep = client.post(
        "/api/root/dependencias", json={"name": "Dep Ask Bot", "description": "desc"}, headers=_auth_headers(root_token)
    ).json()
    general_token = _login_as(role="general")
    sid = "api-ask-bot-no-access"
    history_service.append_turn(sid, "hola", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=dep["id"]),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        client.post("/api/escalate", json={"session_id": sid, "name": "Estudiante", "email": "e@test.com"})

    # El general aún no reclamó esta conversación (sigue asignada a `dep`),
    # así que _ensure_admin_can_act_on_session debe rechazarlo con 403.
    response = client.post(
        f"/api/admin/sessions/{sid}/ask-bot", json={"question": "pregunta"}, headers=_auth_headers(general_token)
    )

    assert response.status_code == 403


def test_ask_bot_returns_draft_without_saving_history():
    from unittest.mock import patch

    token = _login_as(role="general")
    sid = "api-ask-bot-draft"
    history_service.append_turn(sid, "hola", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=None),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        client.post("/api/escalate", json={"session_id": sid, "name": "Estudiante", "email": "e@test.com"})

    history_before = history_service.get_history(sid)

    with (
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
        patch("app.rag.llm.generate_answer", return_value="Respuesta borrador del asistente."),
    ):
        response = client.post(
            f"/api/admin/sessions/{sid}/ask-bot",
            json={"question": "¿pregunta reescrita por el asesor?"},
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Respuesta borrador del asistente."
    assert body["has_sufficient_info"] is True

    history_after = history_service.get_history(sid)
    assert history_after == history_before


def test_ingest_requires_root():
    token = _login_as(role="general")

    response = client.post("/api/ingest", headers=_auth_headers(token))

    assert response.status_code == 403
