"""Orígenes autorizados a embeber el chat (/widget) en un iframe.

La lista vive en SQLite (widget_allowed_origins, ver app/services/history.py)
para que root y el administrador general puedan editarla sin tocar código
ni reiniciar el servidor -- mismo criterio que hostility_service.py para
las palabras del detector de hostilidad. app/main.py la lee en cada
petición a /widget para construir la cabecera CSP frame-ancestors."""
import datetime
import sqlite3
from typing import List
from urllib.parse import urlparse

from app.services import history


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def list_origins() -> List[dict]:
    with history.db_lock():
        conn = history.get_connection()
        rows = conn.execute("SELECT id, origin FROM widget_allowed_origins ORDER BY origin ASC").fetchall()
    return [{"id": row[0], "origin": row[1]} for row in rows]


def add_origin(raw_url: str) -> dict:
    """Acepta la URL completa de una página (p. ej. con ruta) y guarda solo
    su origen real (esquema + host[:puerto]) -- lo único que CSP
    frame-ancestors necesita, y lo único que tiene sentido comparar contra
    el origen que reporta el navegador al embeber el iframe."""
    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f'"{raw_url}" no es una URL válida (debe incluir http:// o https:// y un dominio).')
    normalized = f"{parsed.scheme}://{parsed.netloc}".lower()

    with history.db_lock():
        conn = history.get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO widget_allowed_origins (origin, created_at) VALUES (?, ?)",
                (normalized, _now().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f'"{normalized}" ya está en la lista de orígenes permitidos.')
    return {"id": cursor.lastrowid, "origin": normalized}


def remove_origin(origin_id: int) -> None:
    with history.db_lock():
        conn = history.get_connection()
        conn.execute("DELETE FROM widget_allowed_origins WHERE id = ?", (origin_id,))
        conn.commit()
