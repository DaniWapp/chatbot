"""Agregación de datos para el dashboard de actividad del sistema (root,
general y dependencia -- ver app/api/routes.py::get_dashboard_route).

Todas las secciones se calculan a partir de las mismas tablas que ya usa
el resto del sistema (session_meta/turns para conversaciones,
document_dependencias/discover_documents para documentos, faq_candidates
para FAQ, admins/dependencias para equipo) más las dos tablas nuevas
chat_metrics y groq_calls (ver app/services/history.py), sin mantener
ningún estado propio."""
import datetime
from typing import List, Optional, Tuple

from app.config import settings
from app.services import admin_service
from app.services import history as history_service
from app.services import ingest_service

_TREND_DAYS = 30
_RECENT_WINDOW_DAYS = 7
_RECENT_DOCUMENTS_LIMIT = 5
_UNANSWERED_QUESTIONS_LIMIT = 15


def _cutoff(days: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()


def _avg_minutes(pairs: List[Tuple[Optional[str], Optional[str]]]) -> Optional[float]:
    """pairs son tuplas (inicio_iso, fin_iso); las que tengan algún None se
    ignoran (todavía no ocurrió esa etapa). Devuelve el promedio en
    minutos, o None si ningún par está completo."""
    deltas = []
    for start, end in pairs:
        if not start or not end:
            continue
        delta_minutes = (
            datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(start)
        ).total_seconds() / 60
        deltas.append(delta_minutes)
    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 1)


def _conversations_section(dependencia_id: Optional[int]) -> dict:
    where = "escalated_at IS NOT NULL"
    params: tuple = ()
    if dependencia_id is not None:
        where += " AND dependencia_id = ?"
        params = (dependencia_id,)

    with history_service.db_lock():
        conn = history_service.get_connection()

        total_escalated = conn.execute(f"SELECT COUNT(*) FROM session_meta WHERE {where}", params).fetchone()[0]
        resolved = conn.execute(
            f"SELECT COUNT(*) FROM session_meta WHERE {where} AND resolved_at IS NOT NULL", params
        ).fetchone()[0]
        pending_now = conn.execute(
            f"SELECT COUNT(*) FROM session_meta WHERE {where} AND needs_human = 1", params
        ).fetchone()[0]

        last_7_days = conn.execute(
            f"SELECT COUNT(*) FROM session_meta WHERE {where} AND escalated_at >= ?",
            params + (_cutoff(_RECENT_WINDOW_DAYS),),
        ).fetchone()[0]

        response_pairs = conn.execute(
            f"SELECT dependencia_assigned_at, first_response_at FROM session_meta WHERE {where}", params
        ).fetchall()
        resolution_pairs = conn.execute(
            f"SELECT escalated_at, resolved_at FROM session_meta WHERE {where}", params
        ).fetchall()

        trend_rows = conn.execute(
            f"SELECT substr(escalated_at, 1, 10) AS day, COUNT(*) FROM session_meta "
            f"WHERE {where} AND escalated_at >= ? GROUP BY day ORDER BY day",
            params + (_cutoff(_TREND_DAYS),),
        ).fetchall()

        by_dependencia_rows = []
        if dependencia_id is None:
            by_dependencia_rows = conn.execute(
                "SELECT dependencia_id, COUNT(*) FROM session_meta WHERE escalated_at IS NOT NULL "
                "GROUP BY dependencia_id"
            ).fetchall()

    section = {
        "total_escalated": total_escalated,
        "resolved": resolved,
        "pending_now": pending_now,
        "last_7_days": last_7_days,
        "avg_first_response_minutes": _avg_minutes(response_pairs),
        "avg_resolution_minutes": _avg_minutes(resolution_pairs),
        "daily_trend": [{"date": day, "count": count} for day, count in trend_rows],
    }

    if dependencia_id is None:
        dependencia_names = {d["id"]: d["name"] for d in admin_service.list_dependencias()}
        section["by_dependencia"] = [
            {
                "dependencia_id": dep_id,
                "name": dependencia_names.get(dep_id, "General (sin asignar)"),
                "total": count,
            }
            for dep_id, count in by_dependencia_rows
        ]

    return section


def _documents_section(dependencia_id: Optional[int]) -> dict:
    paths = sorted(ingest_service.discover_documents(), key=lambda p: p.stat().st_mtime, reverse=True)
    infos = [
        {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "dependencia_id": ingest_service.get_document_dependencia(path.name),
            "modified_at": datetime.datetime.fromtimestamp(
                path.stat().st_mtime, tz=datetime.timezone.utc
            ).isoformat(),
        }
        for path in paths
    ]
    if dependencia_id is not None:
        infos = [doc for doc in infos if doc["dependencia_id"] == dependencia_id]

    return {
        "total": len(infos),
        "total_size_bytes": sum(doc["size_bytes"] for doc in infos),
        "recent": [
            {"filename": doc["filename"], "modified_at": doc["modified_at"]}
            for doc in infos[:_RECENT_DOCUMENTS_LIMIT]
        ],
    }


def _faq_section(dependencia_id: Optional[int]) -> dict:
    where = ""
    params: tuple = ()
    if dependencia_id is not None:
        where = "WHERE dependencia_id = ?"
        params = (dependencia_id,)

    with history_service.db_lock():
        conn = history_service.get_connection()
        rows = conn.execute(f"SELECT status, COUNT(*) FROM faq_candidates {where} GROUP BY status", params).fetchall()

    counts = dict(rows)
    return {
        "pending": counts.get("pending", 0),
        "accepted": counts.get("accepted", 0),
        "rejected": counts.get("rejected", 0),
    }


def _admin_team_section() -> dict:
    admins = admin_service.list_admins()
    dependencias = admin_service.list_dependencias()

    active_by_role: dict = {}
    for admin in admins:
        if admin["active"]:
            active_by_role[admin["role"]] = active_by_role.get(admin["role"], 0) + 1

    return {
        "dependencias_count": len(dependencias),
        "admins_active": sum(1 for admin in admins if admin["active"]),
        "admins_inactive": sum(1 for admin in admins if not admin["active"]),
        "admins_active_by_role": active_by_role,
    }


def _performance_section() -> dict:
    with history_service.db_lock():
        conn = history_service.get_connection()

        avg_retrieval_ms, avg_generation_ms, avg_total_ms, total_responses = conn.execute(
            "SELECT AVG(retrieval_ms), AVG(generation_ms), AVG(total_ms), COUNT(*) FROM chat_metrics"
        ).fetchone()
        cache_hits = conn.execute("SELECT COUNT(*) FROM chat_metrics WHERE cache_hit = 1").fetchone()[0]

        groq_calls_total = conn.execute("SELECT COUNT(*) FROM groq_calls").fetchone()[0]
        groq_calls_failed = conn.execute("SELECT COUNT(*) FROM groq_calls WHERE success = 0").fetchone()[0]
        groq_calls_last_7_days = conn.execute(
            "SELECT COUNT(*) FROM groq_calls WHERE created_at >= ?", (_cutoff(_RECENT_WINDOW_DAYS),)
        ).fetchone()[0]

        trend_rows = conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) FROM groq_calls "
            "WHERE created_at >= ? GROUP BY day ORDER BY day",
            (_cutoff(_TREND_DAYS),),
        ).fetchall()

    return {
        "avg_retrieval_ms": round(avg_retrieval_ms, 1) if avg_retrieval_ms is not None else None,
        "avg_generation_ms": round(avg_generation_ms, 1) if avg_generation_ms is not None else None,
        "avg_total_ms": round(avg_total_ms, 1) if avg_total_ms is not None else None,
        "total_responses": total_responses,
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / total_responses * 100, 1) if total_responses else None,
        "groq_calls_total": groq_calls_total,
        "groq_calls_failed": groq_calls_failed,
        "groq_calls_last_7_days": groq_calls_last_7_days,
        "groq_calls_daily_trend": [{"date": day, "count": count} for day, count in trend_rows],
    }


def _unanswered_questions_section() -> dict:
    """Preguntas que dispararon la respuesta fija de "no encontré
    información suficiente" -- la lista priorizada de qué le falta a los
    documentos. No se puede filtrar por dependencia: turns no distingue
    dependencia (solo session_meta la tiene, y solo para conversaciones
    que llegaron a escalarse), así que esta sección es del sistema
    completo, exclusiva de root -- igual que admin_team/performance."""
    with history_service.db_lock():
        conn = history_service.get_connection()
        rows = conn.execute(
            """
            SELECT question, COUNT(*) AS veces, MAX(created_at) AS last_asked
            FROM turns
            WHERE answer LIKE ?
            GROUP BY question
            ORDER BY veces DESC, last_asked DESC
            LIMIT ?
            """,
            (f"%{settings.NO_INFO_MESSAGE.strip()}%", _UNANSWERED_QUESTIONS_LIMIT),
        ).fetchall()

    return {
        "top": [{"question": question, "count": count, "last_asked": last_asked} for question, count, last_asked in rows]
    }


def _feedback_section() -> dict:
    """Totales 👍/👎 y las preguntas peor calificadas -- mide calidad real
    de las respuestas sin revisar conversación por conversación. Mismo
    alcance que unanswered_questions (todo el sistema, exclusivo de root):
    answer_feedback se identifica por session_id+turn_created_at, sin
    columna de dependencia."""
    summary = history_service.get_feedback_summary(limit=_UNANSWERED_QUESTIONS_LIMIT)
    total = summary["up"] + summary["down"]
    return {
        "up": summary["up"],
        "down": summary["down"],
        "down_rate": round(summary["down"] / total * 100, 1) if total else None,
        "most_disliked": summary["most_disliked"],
    }


def get_dashboard(dependencia_id: Optional[int], include_admin_and_performance: bool) -> dict:
    """dependencia_id=None agrega todo el sistema (root y general);
    include_admin_and_performance=True agrega las secciones exclusivas de
    root (equipo de administración, rendimiento/uso de Groq, preguntas sin
    respuesta suficiente, y feedback de respuestas)."""
    dashboard = {
        "conversations": _conversations_section(dependencia_id),
        "documents": _documents_section(dependencia_id),
        "faq": _faq_section(dependencia_id),
    }
    if include_admin_and_performance:
        dashboard["admin_team"] = _admin_team_section()
        dashboard["performance"] = _performance_section()
        dashboard["unanswered_questions"] = _unanswered_questions_section()
        dashboard["feedback"] = _feedback_section()
    return dashboard
