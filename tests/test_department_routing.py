"""Pruebas del ruteo por LLM al escalar: clasificación de dependencia
(app/rag/llm.py:classify_department), filtrado de /api/admin/sessions por
dependencia, control de acceso entre dependencias, y redirección manual.

classify_department y retrieve_context se simulan: no se necesita una
llamada real a Groq ni cargar el modelo de embeddings para probar la
lógica de ruteo/scoping en sí."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.rag import llm
from app.services import admin_service
from app.services import history as history_service

client = TestClient(app)

_counter = 0


def _login_as(role="general", dependencia_id=None, password="clave-segura-123"):
    global _counter
    _counter += 1
    username = f"test-dept-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_dependencia(root_token, name):
    return client.post(
        "/api/root/dependencias", json={"name": name, "description": "desc"}, headers=_auth(root_token)
    ).json()


def _fake_client_returning(json_content):
    fake_client = MagicMock()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json_content))]
    fake_client.chat.completions.create.return_value = completion
    return fake_client


def _escalate(session_id, dependencia_id):
    history_service.append_turn(session_id, "pregunta", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=dependencia_id),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        return client.post(
            "/api/escalate", json={"session_id": session_id, "name": "Estudiante", "email": "e@test.com"}
        )


# --- classify_department (unidad, Groq simulado) ------------------------


@patch("app.rag.llm.get_client")
def test_classify_department_returns_matching_id(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"dependencia_id": 2}')
    deps = [{"id": 1, "name": "A", "description": "a"}, {"id": 2, "name": "B", "description": "b"}]

    assert llm.classify_department("pregunta", deps) == 2


@patch("app.rag.llm.get_client")
def test_classify_department_rejects_unknown_id(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"dependencia_id": 999}')
    deps = [{"id": 1, "name": "A", "description": "a"}]

    assert llm.classify_department("pregunta", deps) is None


@patch("app.rag.llm.get_client")
def test_classify_department_handles_null_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"dependencia_id": null}')
    deps = [{"id": 1, "name": "A", "description": "a"}]

    assert llm.classify_department("pregunta", deps) is None


@patch("app.rag.llm.get_client")
def test_classify_department_handles_malformed_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("esto no es json")
    deps = [{"id": 1, "name": "A", "description": "a"}]

    assert llm.classify_department("pregunta", deps) is None


def test_classify_department_returns_none_without_dependencias():
    assert llm.classify_department("pregunta", []) is None


# --- /api/escalate asigna la dependencia decidida por el LLM ------------


def test_escalate_assigns_dependencia_from_llm_classification():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep Ruteo")

    res = _escalate("dept-route-1", dep["id"])

    assert res.status_code == 200
    assert res.json()["dependencia_id"] == dep["id"]
    assert history_service.get_session_meta("dept-route-1")["dependencia_id"] == dep["id"]


# --- filtrado de /api/admin/sessions por dependencia ---------------------


def test_dependencia_admin_only_sees_own_sessions():
    root_token = _login_as(role="root")
    dep_a = _create_dependencia(root_token, "Dep A")
    dep_b = _create_dependencia(root_token, "Dep B")

    _escalate("dept-scope-a", dep_a["id"])
    _escalate("dept-scope-b", dep_b["id"])

    token_a = _login_as(role="dependencia", dependencia_id=dep_a["id"])
    sessions_a = client.get("/api/admin/sessions", headers=_auth(token_a)).json()["sessions"]
    ids_a = {s["session_id"] for s in sessions_a}

    assert "dept-scope-a" in ids_a
    assert "dept-scope-b" not in ids_a


def test_general_admin_sees_only_unclassified_escalations():
    _escalate("dept-scope-general", None)

    token_general = _login_as(role="general")
    sessions = client.get("/api/admin/sessions", headers=_auth(token_general)).json()["sessions"]

    assert any(s["session_id"] == "dept-scope-general" for s in sessions)


def test_unescalated_session_never_appears_for_any_admin():
    history_service.append_turn("dept-never-escalated", "hola", "respuesta")

    token_general = _login_as(role="general")
    sessions = client.get("/api/admin/sessions", headers=_auth(token_general)).json()["sessions"]

    assert not any(s["session_id"] == "dept-never-escalated" for s in sessions)


# --- control de acceso entre dependencias ---------------------------------


def test_dependencia_admin_cannot_access_other_dependencia_session():
    root_token = _login_as(role="root")
    dep_a = _create_dependencia(root_token, "Dep C")
    dep_b = _create_dependencia(root_token, "Dep D")

    _escalate("dept-access-check", dep_a["id"])

    token_b = _login_as(role="dependencia", dependencia_id=dep_b["id"])
    res = client.get("/api/admin/sessions/dept-access-check/messages", headers=_auth(token_b))

    assert res.status_code == 403


def test_general_admin_cannot_access_dependencia_session():
    root_token = _login_as(role="root")
    dep = _create_dependencia(root_token, "Dep G")
    _escalate("dept-access-check-2", dep["id"])

    token_general = _login_as(role="general")
    res = client.post("/api/admin/sessions/dept-access-check-2/resolve", headers=_auth(token_general))

    assert res.status_code == 403


# --- redirección manual ---------------------------------------------------


def test_manual_reassignment_moves_session_between_queues():
    root_token = _login_as(role="root")
    dep_a = _create_dependencia(root_token, "Dep E")
    dep_b = _create_dependencia(root_token, "Dep F")

    _escalate("dept-reassign", dep_a["id"])

    token_a = _login_as(role="dependencia", dependencia_id=dep_a["id"])
    reassign_res = client.post(
        "/api/admin/sessions/dept-reassign/reassign", json={"dependencia_id": dep_b["id"]}, headers=_auth(token_a)
    )
    assert reassign_res.status_code == 200

    token_b = _login_as(role="dependencia", dependencia_id=dep_b["id"])
    sessions_b = client.get("/api/admin/sessions", headers=_auth(token_b)).json()["sessions"]
    assert any(s["session_id"] == "dept-reassign" for s in sessions_b)

    sessions_a_after = client.get("/api/admin/sessions", headers=_auth(token_a)).json()["sessions"]
    assert not any(s["session_id"] == "dept-reassign" for s in sessions_a_after)


def test_reassign_to_general_requires_current_access():
    root_token = _login_as(role="root")
    dep_a = _create_dependencia(root_token, "Dep H")
    dep_b = _create_dependencia(root_token, "Dep I")
    _escalate("dept-reassign-blocked", dep_a["id"])

    token_b = _login_as(role="dependencia", dependencia_id=dep_b["id"])
    res = client.post(
        "/api/admin/sessions/dept-reassign-blocked/reassign", json={"dependencia_id": None}, headers=_auth(token_b)
    )

    assert res.status_code == 403
