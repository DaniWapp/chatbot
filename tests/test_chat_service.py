"""Pruebas de detección de saludos/agradecimientos (small talk).

Los saludos se responden directo, sin pasar por la búsqueda semántica ni el
LLM, para no responder "no encontré información" ante un simple "hola".
"""
import pytest

from app.services.chat_service import _smalltalk_reply


@pytest.mark.parametrize(
    "message",
    [
        "hola",
        "Hola!",
        "holis",
        "holaaa",
        "ola",
        "olis",
        "buenas",
        "buenos días",
        "buenas tardes",
        "qué tal",
        "q tal",
        "qué más",
        "quiubo",
        "quihubo",
        "qué onda",
        "hey",
        "hi",
        "hello",
        "saludos",
        "gracias",
        "muchas gracias",
    ],
)
def test_greetings_and_thanks_are_detected(message):
    assert _smalltalk_reply(message) is not None


@pytest.mark.parametrize(
    "message",
    [
        "valor de la matrícula",
        "¿Cuáles son los requisitos para graduarme?",
        "hola cuales son los requisitos",
        "holis, cuanto cuesta la matricula",
    ],
)
def test_real_questions_are_not_treated_as_smalltalk(message):
    assert _smalltalk_reply(message) is None
