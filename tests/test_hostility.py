"""Pruebas del detector de hostilidad hacia el chatbot
(app/services/hostility_service.py): detección por lista de palabras,
CRUD de la lista, y el ciclo de strikes -> bloqueo por sesión."""
import uuid

import pytest

from app.config import settings
from app.services import hostility_service


def _session_id() -> str:
    return f"hostility-test-{uuid.uuid4().hex[:8]}"


def test_contains_hostile_language_detects_seeded_keyword():
    assert hostility_service.contains_hostile_language("eres un idiota") is True


def test_contains_hostile_language_ignores_clean_message():
    assert hostility_service.contains_hostile_language("¿cuándo empiezan las matrículas?") is False


def test_contains_hostile_language_no_false_positive_on_substring():
    """"puta" está en la lista semilla, pero es substring literal de
    "reputación" -- el detector debe usar límite de palabra, no un simple
    "in", para no marcar esto como hostil."""
    assert hostility_service.contains_hostile_language("estamos evaluando su reputación académica") is False


def test_add_list_and_remove_keyword():
    phrase = f"zzz-test-palabra-{uuid.uuid4().hex[:6]}"

    created = hostility_service.add_keyword(phrase)
    assert created["phrase"] == phrase
    assert any(k["phrase"] == phrase for k in hostility_service.list_keywords())
    assert hostility_service.contains_hostile_language(f"esto es {phrase} de verdad") is True

    hostility_service.remove_keyword(created["id"])
    assert not any(k["phrase"] == phrase for k in hostility_service.list_keywords())
    assert hostility_service.contains_hostile_language(f"esto es {phrase} de verdad") is False


def test_add_duplicate_keyword_raises():
    phrase = f"zzz-test-duplicado-{uuid.uuid4().hex[:6]}"
    hostility_service.add_keyword(phrase)

    with pytest.raises(ValueError):
        hostility_service.add_keyword(phrase)


def test_get_status_defaults_for_unknown_session():
    status = hostility_service.get_status(_session_id())
    assert status == {"strikes": 0, "blocked_until": None}


def test_register_strike_increments_and_blocks_at_limit(monkeypatch):
    monkeypatch.setattr(settings, "HOSTILITY_STRIKE_LIMIT", 2)
    monkeypatch.setattr(settings, "HOSTILITY_BLOCK_HOURS", 1.0)
    session_id = _session_id()

    first = hostility_service.register_strike(session_id)
    assert first == {"strikes": 1, "blocked_until": None}

    second = hostility_service.register_strike(session_id)
    assert second["strikes"] == 0
    assert second["blocked_until"] is not None

    status = hostility_service.get_status(session_id)
    assert status["blocked_until"] == second["blocked_until"]


def test_check_and_intercept_full_flow(monkeypatch):
    monkeypatch.setattr(settings, "HOSTILITY_STRIKE_LIMIT", 2)
    monkeypatch.setattr(settings, "HOSTILITY_BLOCK_HOURS", 1.0)
    session_id = _session_id()

    assert hostility_service.check_and_intercept(session_id, "hola, buenas tardes") is None

    warning = hostility_service.check_and_intercept(session_id, "eres un idiota")
    assert "1/2" in warning

    blocked_notice = hostility_service.check_and_intercept(session_id, "eres un idiota")
    assert "bloqueado" in blocked_notice.lower()

    still_blocked = hostility_service.check_and_intercept(session_id, "hola de nuevo")
    assert "sigue bloqueado" in still_blocked.lower()
