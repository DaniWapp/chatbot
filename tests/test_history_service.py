"""Pruebas del servicio de historial (app/services/history.py): paginación
de la lista de sesiones, paginación de mensajes dentro de una conversación
(incluyendo el caso límite de mensajes con el mismo created_at) y el flujo
de escalamiento / chequeo "¿algo más?"."""
from app.services import history as history_service


def test_list_sessions_pagination_covers_all_without_duplicates():
    session_ids = [f"hist-pag-{i}" for i in range(5)]
    for sid in session_ids:
        history_service.append_turn(sid, "pregunta", "respuesta")

    first_page = history_service.list_sessions(offset=0, limit=2)
    assert len(first_page["sessions"]) == 2
    assert first_page["has_more"] is True
    assert first_page["total"] >= len(session_ids)

    seen_ids = []
    offset = 0
    while True:
        page = history_service.list_sessions(offset=offset, limit=2)
        seen_ids.extend(s["session_id"] for s in page["sessions"])
        offset += len(page["sessions"])
        if not page["has_more"]:
            break

    assert len(seen_ids) == len(set(seen_ids))  # sin duplicados entre páginas
    assert set(session_ids) <= set(seen_ids)


def test_list_sessions_needs_human_only_filters_and_tracks_pending_count():
    sid = "hist-pending-1"
    history_service.append_turn(sid, "pregunta", "respuesta")
    history_service.escalate_session(sid, "Estudiante Test", "test@test.com")

    pending = history_service.list_sessions(needs_human_only=True)
    assert any(s["session_id"] == sid for s in pending["sessions"])
    assert pending["pending_count"] >= 1
    assert pending["has_more"] is False  # needs_human_only trae todas de una vez

    history_service.resolve_session(sid, resolved_by="advisor")

    pending_after = history_service.list_sessions(needs_human_only=True)
    assert all(s["session_id"] != sid for s in pending_after["sessions"])


def test_get_history_page_cursor_survives_split_pair():
    """La pregunta y la respuesta de un turno comparten el mismo
    created_at. Con limit=1, el corte de página cae justo entre ambas: el
    cursor debe seguir trayendo la pregunta en la página siguiente en vez
    de perderla (bug real encontrado durante el desarrollo)."""
    sid = "hist-tiebreak-split"
    history_service.append_turn(sid, "unica pregunta", "unica respuesta")

    page1 = history_service.get_history_page(sid, limit=1)
    assert len(page1["messages"]) == 1
    assert page1["messages"][0]["sender"] == "assistant"
    assert page1["has_more"] is True
    assert page1["next_cursor"]

    page2 = history_service.get_history_page(sid, before=page1["next_cursor"], limit=1)
    assert len(page2["messages"]) == 1
    assert page2["messages"][0]["sender"] == "student"
    assert page2["has_more"] is False


def test_get_history_page_walks_all_messages_in_order_without_loss():
    sid = "hist-tiebreak-walk"
    for i in range(6):
        history_service.append_turn(sid, f"pregunta {i}", f"respuesta {i}")

    seen = []
    before = None
    while True:
        page = history_service.get_history_page(sid, before=before, limit=3)
        seen = page["messages"] + seen
        if not page["has_more"]:
            break
        before = page["next_cursor"]

    assert len(seen) == 12  # 6 turnos x 2 mensajes
    assert len({(m["created_at"], m["sender"], m["message"]) for m in seen}) == 12
    for i in range(0, 12, 2):
        assert seen[i]["sender"] == "student"
        assert seen[i + 1]["sender"] == "assistant"
        assert seen[i]["created_at"] == seen[i + 1]["created_at"]


def test_ask_continue_checkin_flow_resolves_on_no():
    sid = "hist-checkin-no"
    history_service.append_turn(sid, "pregunta", "respuesta")
    history_service.escalate_session(sid, "Estudiante", "e@test.com")

    history_service.add_admin_message(sid, "advisor", "¿Te puedo ayudar con algo más?", message_type="checkin")
    history_service.add_admin_message(sid, "student", "No, gracias", message_type="checkin_response")
    history_service.resolve_session(sid, resolved_by="student")

    assert history_service.get_session_meta(sid)["needs_human"] is False

    page = history_service.get_history_page(sid, limit=50)
    checkins = [m for m in page["messages"] if m["message_type"] == "checkin"]
    responses = [m for m in page["messages"] if m["message_type"] == "checkin_response"]
    assert len(checkins) == 1
    assert len(responses) == 1
    assert responses[0]["message"] == "No, gracias"


def test_ask_continue_checkin_flow_keeps_escalated_on_yes():
    sid = "hist-checkin-yes"
    history_service.append_turn(sid, "pregunta", "respuesta")
    history_service.escalate_session(sid, "Estudiante", "e@test.com")

    history_service.add_admin_message(sid, "advisor", "¿Te puedo ayudar con algo más?", message_type="checkin")
    history_service.add_admin_message(sid, "student", "Sí, por favor", message_type="checkin_response")

    # A diferencia del caso "No", aquí nadie llama a resolve_session: la
    # sesión debe seguir escalada.
    assert history_service.get_session_meta(sid)["needs_human"] is True
