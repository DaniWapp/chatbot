"""Pruebas de app/services/ws_manager.py::is_session_connected -- usado
por el panel para saber si el estudiante sigue con el chat abierto ahora
mismo (ver app/api/routes.py::list_sessions)."""
import asyncio
from unittest.mock import AsyncMock

from app.services import ws_manager


def test_is_session_connected_false_when_never_connected():
    assert ws_manager.is_session_connected("ws-test-never-connected") is False


def test_is_session_connected_true_after_connect_false_after_disconnect():
    fake_ws = AsyncMock()
    session_id = "ws-test-presence"

    asyncio.run(ws_manager.connect_session(session_id, fake_ws))
    assert ws_manager.is_session_connected(session_id) is True

    ws_manager.disconnect_session(session_id, fake_ws)
    assert ws_manager.is_session_connected(session_id) is False
