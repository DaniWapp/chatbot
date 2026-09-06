"""Detección de hostilidad hacia el chatbot y bloqueo temporal por sesión.

Detección por lista de palabras/frases (no por LLM): gratis e instantánea,
sin gastar cupo de Groq en cada mensaje -- mismo criterio ya aplicado con
el re-ranking local (app/rag/reranker.py). La lista vive en SQLite
(hostility_keywords, ver app/services/history.py) para que root y el
administrador general puedan editarla sin tocar código.

El bloqueo es por session_id, no por IP: más fácil de evitar (una sesión
nueva en incógnito), pero sin riesgo de afectar a otros estudiantes que
compartan la misma red."""
import datetime
import re
import sqlite3
from typing import List, Optional

from app.config import settings
from app.services import history


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def list_keywords() -> List[dict]:
    with history.db_lock():
        conn = history.get_connection()
        rows = conn.execute("SELECT id, phrase FROM hostility_keywords ORDER BY phrase ASC").fetchall()
    return [{"id": row[0], "phrase": row[1]} for row in rows]


def add_keyword(phrase: str) -> dict:
    normalized = phrase.strip().lower()
    with history.db_lock():
        conn = history.get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO hostility_keywords (phrase, created_at) VALUES (?, ?)",
                (normalized, _now().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f'La palabra/frase "{normalized}" ya está en la lista.')
    return {"id": cursor.lastrowid, "phrase": normalized}


def remove_keyword(keyword_id: int) -> None:
    with history.db_lock():
        conn = history.get_connection()
        conn.execute("DELETE FROM hostility_keywords WHERE id = ?", (keyword_id,))
        conn.commit()


def contains_hostile_language(message: str) -> bool:
    """Compara cada palabra clave contra el mensaje con límite de palabra
    (\\b) -- un simple "in" marcaría falsos positivos reales (ej. "puta"
    es substring literal de "reputación")."""
    keywords = [k["phrase"] for k in list_keywords()]
    return any(re.search(rf"\b{re.escape(kw)}\b", message, re.IGNORECASE) for kw in keywords)


def get_status(session_id: str) -> dict:
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            "SELECT hostility_strikes, hostility_blocked_until FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return {"strikes": 0, "blocked_until": None}
    return {"strikes": row[0], "blocked_until": row[1]}


def register_strike(session_id: str) -> dict:
    """Suma un strike a la sesión (UPSERT: funciona aunque la sesión nunca
    haya tenido fila en session_meta). Si llega al límite, fija
    hostility_blocked_until y reinicia el contador a 0."""
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            """
            INSERT INTO session_meta (session_id, hostility_strikes)
            VALUES (?, 1)
            ON CONFLICT(session_id) DO UPDATE SET
                hostility_strikes = hostility_strikes + 1
            """,
            (session_id,),
        )
        strikes = conn.execute(
            "SELECT hostility_strikes FROM session_meta WHERE session_id = ?", (session_id,)
        ).fetchone()[0]

        blocked_until = None
        if strikes >= settings.HOSTILITY_STRIKE_LIMIT:
            blocked_until = (_now() + datetime.timedelta(hours=settings.HOSTILITY_BLOCK_HOURS)).isoformat()
            conn.execute(
                "UPDATE session_meta SET hostility_strikes = 0, hostility_blocked_until = ? WHERE session_id = ?",
                (blocked_until, session_id),
            )
            strikes = 0
        conn.commit()
    return {"strikes": strikes, "blocked_until": blocked_until}


def _format_remaining(blocked_until_iso: str) -> str:
    remaining = datetime.datetime.fromisoformat(blocked_until_iso) - _now()
    total_minutes = max(1, int(remaining.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} hora{'s' if hours != 1 else ''} y {minutes} minuto{'s' if minutes != 1 else ''}"
    if hours:
        return f"{hours} hora{'s' if hours != 1 else ''}"
    return f"{minutes} minuto{'s' if minutes != 1 else ''}"


_STRIKE_WARNING = (
    "Por favor mantén un tono respetuoso. Este es un aviso ({strikes}/{limit}) -- "
    "si vuelve a ocurrir, tu acceso al chat se bloqueará temporalmente."
)
_BLOCK_TRIGGERED = (
    "Tu acceso al chat ha sido bloqueado temporalmente por lenguaje inapropiado repetido. "
    "Podrás volver a escribir en {remaining}."
)
_ALREADY_BLOCKED = (
    "Tu acceso al chat sigue bloqueado por lenguaje inapropiado. "
    "Podrás volver a escribir en {remaining}."
)


def check_and_intercept(session_id: str, message: str) -> Optional[str]:
    """Devuelve el texto a mostrar en vez de procesar el mensaje
    normalmente, o None si el mensaje debe seguir su curso habitual.
    Cubre los 3 casos: la sesión ya está bloqueada, el mensaje es hostil y
    dispara un bloqueo nuevo, o el mensaje es hostil pero todavía no llega
    al límite."""
    status = get_status(session_id)
    if status["blocked_until"] and status["blocked_until"] > _now().isoformat():
        return _ALREADY_BLOCKED.format(remaining=_format_remaining(status["blocked_until"]))

    if not contains_hostile_language(message):
        return None

    result = register_strike(session_id)
    if result["blocked_until"]:
        return _BLOCK_TRIGGERED.format(remaining=_format_remaining(result["blocked_until"]))
    return _STRIKE_WARNING.format(strikes=result["strikes"], limit=settings.HOSTILITY_STRIKE_LIMIT)
