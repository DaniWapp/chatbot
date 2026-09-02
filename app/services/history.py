"""Historial de conversación en memoria, por sesión (sin base de datos: alcanza
para un proyecto académico de un solo proceso). Se limita a los últimos N
turnos para no inflar el prompt enviado al LLM."""
import threading
from collections import defaultdict, deque
from typing import Deque, Dict, List, Tuple

from app.config import settings

_lock = threading.Lock()
_sessions: Dict[str, Deque[Tuple[str, str]]] = defaultdict(
    lambda: deque(maxlen=settings.MAX_HISTORY_TURNS)
)


def get_history(session_id: str) -> List[Tuple[str, str]]:
    with _lock:
        return list(_sessions[session_id])


def append_turn(session_id: str, question: str, answer: str) -> None:
    with _lock:
        _sessions[session_id].append((question, answer))


def clear_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)
