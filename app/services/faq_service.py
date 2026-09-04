"""Propuestas de preguntas frecuentes generadas automáticamente al resolver
una conversación escalada que sí llegó a tener respuesta de un asesor. El
root las revisa, edita si hace falta, y las acepta o descarta desde
/root -- ver app/api/routes.py para el flujo de aceptación (agregar al
archivo de FAQ correspondiente + reingesta).
"""
import datetime
from typing import List, Optional

from app.services import history

VALID_STATUSES = {"pending", "accepted", "rejected"}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _row_to_candidate(row) -> dict:
    (
        candidate_id,
        session_id,
        dependencia_id,
        original_question,
        original_answer,
        suggested_question,
        suggested_answer,
        status,
        created_at,
        decided_at,
    ) = row
    return {
        "id": candidate_id,
        "session_id": session_id,
        "dependencia_id": dependencia_id,
        "original_question": original_question,
        "original_answer": original_answer,
        "suggested_question": suggested_question,
        "suggested_answer": suggested_answer,
        "status": status,
        "created_at": created_at,
        "decided_at": decided_at,
    }


_COLUMNS = (
    "id, session_id, dependencia_id, original_question, original_answer, "
    "suggested_question, suggested_answer, status, created_at, decided_at"
)


def create_candidate(
    session_id: str,
    dependencia_id: Optional[int],
    original_question: str,
    original_answer: str,
    suggested_question: str,
    suggested_answer: str,
) -> int:
    with history.db_lock():
        conn = history.get_connection()
        cursor = conn.execute(
            """
            INSERT INTO faq_candidates
                (session_id, dependencia_id, original_question, original_answer,
                 suggested_question, suggested_answer, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (session_id, dependencia_id, original_question, original_answer, suggested_question, suggested_answer, _now()),
        )
        conn.commit()
        return cursor.lastrowid


def list_candidates(status: Optional[str] = "pending") -> List[dict]:
    """status=None trae todas (pendientes, aceptadas y descartadas); por
    defecto solo las pendientes, que es lo que el root necesita revisar."""
    with history.db_lock():
        conn = history.get_connection()
        if status is None:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM faq_candidates ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM faq_candidates WHERE status = ? ORDER BY created_at ASC", (status,)
            ).fetchall()
    return [_row_to_candidate(r) for r in rows]


def get_candidate(candidate_id: int) -> Optional[dict]:
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(f"SELECT {_COLUMNS} FROM faq_candidates WHERE id = ?", (candidate_id,)).fetchone()
    return _row_to_candidate(row) if row else None


def update_candidate_text(candidate_id: int, question: str, answer: str) -> None:
    """El root puede editar la pregunta/respuesta sugeridas antes de
    aceptarlas. Solo tiene sentido sobre una propuesta todavía pendiente."""
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "UPDATE faq_candidates SET suggested_question = ?, suggested_answer = ? WHERE id = ? AND status = 'pending'",
            (question, answer, candidate_id),
        )
        conn.commit()


def mark_decided(candidate_id: int, status: str) -> str:
    if status not in ("accepted", "rejected"):
        raise ValueError(f"Estado inválido: {status!r}")
    decided_at = _now()
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "UPDATE faq_candidates SET status = ?, decided_at = ? WHERE id = ?", (status, decided_at, candidate_id)
        )
        conn.commit()
    return decided_at
