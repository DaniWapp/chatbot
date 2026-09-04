"""Pruebas de las propuestas automáticas de preguntas frecuentes: se
generan al resolver una conversación escalada que sí tuvo respuesta de un
asesor, el root las revisa/edita/acepta o descarta, y aceptarlas agrega la
entrada al archivo de FAQ de la dependencia correspondiente + reingesta.

classify_department, generate_faq_candidate, retrieve_context, embed_texts
y vector_store se simulan: no se necesita una llamada real a Groq ni cargar
el modelo de embeddings para probar esta lógica."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.rag import llm
from app.services import admin_service
from app.services import faq_service
from app.services import history as history_service


def _fake_client_returning(json_content):
    fake_client = MagicMock()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json_content))]
    fake_client.chat.completions.create.return_value = completion
    return fake_client

client = TestClient(app)

_counter = 0

_FAKE_SUGGESTION = {
    "question": "¿Pregunta reescrita de forma profesional?",
    "answer": "Respuesta reescrita de forma profesional y completa.",
}


def _login_as(role="root", dependencia_id=None, password="clave-segura-123"):
    global _counter
    _counter += 1
    username = f"test-faq-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _escalate_and_resolve(session_id, dependencia_id, admin_token=None, advisor_message=None, resolve_as="student"):
    """Sienta una conversación escalada (opcionalmente con una respuesta de
    asesor, si se da admin_token + advisor_message) y la resuelve --como
    asesor (resolve_as='advisor', requiere admin_token) o como el propio
    estudiante (resolve_as='student', default)--, con
    classify_department/generate_faq_candidate simulados."""
    history_service.append_turn(session_id, "pregunta de prueba", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=dependencia_id),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        client.post("/api/escalate", json={"session_id": session_id, "name": "Est", "email": "e@test.com"})

    if advisor_message:
        assert admin_token, "advisor_message requiere admin_token para poder enviarlo"
        client.post(
            f"/api/admin/sessions/{session_id}/reply", json={"message": advisor_message}, headers=_auth(admin_token)
        )

    with (
        patch("app.rag.llm.generate_faq_candidate", return_value=_FAKE_SUGGESTION) as mock_generate,
        patch("app.api.routes._find_similar_accepted_faqs", return_value=[]),
    ):
        if resolve_as == "advisor":
            assert admin_token, "resolve_as='advisor' requiere admin_token"
            client.post(f"/api/admin/sessions/{session_id}/resolve", headers=_auth(admin_token))
        else:
            client.post(f"/api/sessions/{session_id}/mark-solved")
    return mock_generate


def test_resolving_with_advisor_reply_creates_pending_candidate():
    root_token = _login_as(role="root")
    general_token = _login_as(role="general")
    sid = "faq-with-reply"

    mock_generate = _escalate_and_resolve(sid, None, admin_token=general_token, advisor_message="Aquí está la respuesta")
    mock_generate.assert_called_once()

    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    assert any(c["session_id"] == sid for c in pending)


def test_resolving_without_any_advisor_reply_creates_no_candidate():
    root_token = _login_as(role="root")
    sid = "faq-no-reply"

    mock_generate = _escalate_and_resolve(sid, None)
    mock_generate.assert_not_called()

    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    assert not any(c["session_id"] == sid for c in pending)


def test_resolving_skips_candidate_when_llm_detects_duplicate_of_accepted_faq():
    """Ver caso real: la misma información ("¿Ofrecen la carrera de
    Sistemas?") ya aceptada antes, propuesta de nuevo con otra redacción --
    no debe crear un segundo candidato pendiente."""
    root_token = _login_as(role="root")
    general_token = _login_as(role="general")
    sid = "faq-duplicate-of-accepted"
    history_service.append_turn(sid, "pregunta de prueba", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=None),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        client.post("/api/escalate", json={"session_id": sid, "name": "Est", "email": "e@test.com"})
    client.post(
        f"/api/admin/sessions/{sid}/reply",
        json={"message": "Aquí está la respuesta"},
        headers=_auth(general_token),
    )

    with (
        patch("app.rag.llm.generate_faq_candidate", return_value=_FAKE_SUGGESTION),
        patch(
            "app.api.routes._find_similar_accepted_faqs",
            return_value=["Pregunta: ¿Ofrecen la carrera de Sistemas? Respuesta: No contamos con..."],
        ),
        patch("app.rag.llm.is_duplicate_faq", return_value=True) as mock_is_duplicate,
    ):
        client.post(f"/api/admin/sessions/{sid}/resolve", headers=_auth(general_token))

    mock_is_duplicate.assert_called_once()
    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    assert not any(c["session_id"] == sid for c in pending)


def test_checkin_only_message_does_not_count_as_a_real_answer():
    """El chequeo automático "¿algo más?" no es una respuesta a la
    pregunta: no debe generar una propuesta de FAQ por sí solo."""
    root_token = _login_as(role="root")
    sid = "faq-checkin-only"
    history_service.append_turn(sid, "pregunta", "respuesta")
    with (
        patch("app.rag.llm.classify_department", return_value=None),
        patch("app.services.chat_service.retrieve_context", return_value=([], 0.0)),
    ):
        client.post("/api/escalate", json={"session_id": sid, "name": "Est", "email": "e@test.com"})

    dep_token = _login_as(role="general")
    client.post(f"/api/admin/sessions/{sid}/ask-continue", headers=_auth(dep_token))

    with patch("app.rag.llm.generate_faq_candidate") as mock_generate:
        client.post(f"/api/sessions/{sid}/mark-solved")
    mock_generate.assert_not_called()


def test_candidate_inherits_session_dependencia():
    root_token = _login_as(role="root")
    dep = client.post(
        "/api/root/dependencias", json={"name": "Dep FAQ Inherit", "description": "desc"}, headers=_auth(root_token)
    ).json()
    dep_token = _login_as(role="dependencia", dependencia_id=dep["id"])
    sid = "faq-inherit-dep"

    _escalate_and_resolve(sid, dep["id"], admin_token=dep_token, advisor_message="Respuesta del asesor", resolve_as="advisor")

    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    candidate = next(c for c in pending if c["session_id"] == sid)
    assert candidate["dependencia_id"] == dep["id"]


def test_faq_routes_require_root():
    token = _login_as(role="general")
    assert client.get("/api/root/faq-candidates", headers=_auth(token)).status_code == 403


def test_update_and_reject_candidate():
    root_token = _login_as(role="root")
    general_token = _login_as(role="general")
    sid = "faq-update-reject"
    _escalate_and_resolve(sid, None, admin_token=general_token, advisor_message="Respuesta original")

    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    candidate = next(c for c in pending if c["session_id"] == sid)

    update_res = client.put(
        f"/api/root/faq-candidates/{candidate['id']}",
        json={"question": "Pregunta editada", "answer": "Respuesta editada"},
        headers=_auth(root_token),
    )
    assert update_res.status_code == 200
    assert update_res.json()["suggested_question"] == "Pregunta editada"

    reject_res = client.post(f"/api/root/faq-candidates/{candidate['id']}/reject", headers=_auth(root_token))
    assert reject_res.status_code == 200

    pending_after = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    assert not any(c["id"] == candidate["id"] for c in pending_after)


def test_accept_candidate_writes_file_and_reingests(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)

    root_token = _login_as(role="root")
    general_token = _login_as(role="general")
    sid = "faq-accept-flow"
    _escalate_and_resolve(sid, None, admin_token=general_token, advisor_message="Respuesta a aceptar")

    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    candidate = next(c for c in pending if c["session_id"] == sid)

    with (
        patch("app.services.ingest_service.embed_texts", return_value=[[0.1, 0.2, 0.3]]),
        patch("app.services.ingest_service.vector_store.add_chunks"),
        patch("app.services.ingest_service.vector_store.reset_collection"),
    ):
        accept_res = client.post(f"/api/root/faq-candidates/{candidate['id']}/accept", headers=_auth(root_token))

    assert accept_res.status_code == 200
    assert accept_res.json()["documents_processed"] >= 1

    faq_file = tmp_path / "faq_generadas_general.txt"
    assert faq_file.exists()
    content = faq_file.read_text(encoding="utf-8")
    assert _FAKE_SUGGESTION["question"] in content
    assert _FAKE_SUGGESTION["answer"] in content

    assert faq_service.get_candidate(candidate["id"])["status"] == "accepted"


def test_accept_already_decided_candidate_is_rejected_with_409():
    root_token = _login_as(role="root")
    general_token = _login_as(role="general")
    sid = "faq-double-accept"
    _escalate_and_resolve(sid, None, admin_token=general_token, advisor_message="Respuesta")

    pending = client.get("/api/root/faq-candidates?status=pending", headers=_auth(root_token)).json()
    candidate = next(c for c in pending if c["session_id"] == sid)
    client.post(f"/api/root/faq-candidates/{candidate['id']}/reject", headers=_auth(root_token))

    res = client.post(f"/api/root/faq-candidates/{candidate['id']}/accept", headers=_auth(root_token))
    assert res.status_code == 409


# --- llm.is_duplicate_faq (unidad, Groq simulado) ------------------------


@patch("app.rag.llm.get_client")
def test_is_duplicate_faq_returns_true_when_llm_says_so(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"is_duplicate": true}')

    result = llm.is_duplicate_faq(
        "¿La facultad ofrece la carrera de Ingeniería en Sistemas?",
        "No, ofrece Ingeniería en TIC.",
        ["Pregunta: ¿Ofrecen la carrera de Sistemas? Respuesta: No contamos con..."],
    )

    assert result is True


@patch("app.rag.llm.get_client")
def test_is_duplicate_faq_returns_false_when_llm_says_so(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"is_duplicate": false}')

    result = llm.is_duplicate_faq(
        "¿Cuál es el horario de la biblioteca?",
        "La biblioteca abre de 7am a 9pm.",
        ["Pregunta: ¿Ofrecen la carrera de Sistemas? Respuesta: No contamos con..."],
    )

    assert result is False


@patch("app.rag.llm.get_client")
def test_is_duplicate_faq_handles_malformed_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("esto no es json")

    assert llm.is_duplicate_faq("pregunta", "respuesta", ["algo existente"]) is False


@patch("app.rag.llm.get_client")
def test_is_duplicate_faq_handles_client_exception(mock_get_client):
    mock_get_client.side_effect = RuntimeError("groq caído")

    assert llm.is_duplicate_faq("pregunta", "respuesta", ["algo existente"]) is False


def test_is_duplicate_faq_returns_false_without_similar_existing():
    assert llm.is_duplicate_faq("pregunta", "respuesta", []) is False
