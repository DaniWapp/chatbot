"""Historial de conversación persistente (SQLite), por sesión.

Tres tablas de conversación:
- turns: cada intercambio pregunta/respuesta del chatbot (usado para dar
  contexto al LLM y para la transcripción del panel).
- session_meta: estado de escalamiento a un asesor humano por sesión
  (needs_human, datos del estudiante, timestamps, a qué dependencia quedó
  asignada).
- admin_messages: mensajes intercambiados entre estudiante y asesor
  DESPUÉS de escalar (el bot ya no participa en esta conversación).

Más las tablas de administración (dependencias, cuentas de administrador,
sesiones de login e información de la institución), creadas en el mismo
bloque de inicialización de esquema -- toda la app comparte una sola
conexión SQLite y un solo lock, expuestos aquí (get_connection/
ensure_column) para que app/services/admin_service.py los reutilice sin
duplicar el manejo de la conexión."""
import datetime
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_connection: sqlite3.Connection = None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Agrega una columna a una tabla existente si todavía no la tiene.
    CREATE TABLE IF NOT EXISTS no modifica tablas ya creadas en ejecuciones
    anteriores, así que los cambios de esquema necesitan esta migración
    mínima e idempotente."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        settings.HISTORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(str(settings.HISTORY_DB_PATH), check_same_thread=False)
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _connection.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id)")
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_meta (
                session_id TEXT PRIMARY KEY,
                needs_human INTEGER NOT NULL DEFAULT 0,
                student_name TEXT,
                student_email TEXT,
                escalated_at TEXT,
                resolved_at TEXT,
                resolved_by TEXT
            )
            """
        )
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _connection.execute("CREATE INDEX IF NOT EXISTS idx_admin_messages_session ON admin_messages(session_id)")
        _ensure_column(_connection, "session_meta", "resolved_by", "TEXT")
        _ensure_column(_connection, "admin_messages", "message_type", "TEXT NOT NULL DEFAULT 'text'")

        # --- Administración: dependencias, cuentas de administrador, sesiones ---
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dependencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                dependencia_id INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                admin_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        _connection.execute("CREATE INDEX IF NOT EXISTS idx_admin_sessions_admin ON admin_sessions(admin_id)")
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS institution_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT NOT NULL,
                logo_filename TEXT,
                extra_info TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(_connection, "session_meta", "dependencia_id", "INTEGER")
        _ensure_column(_connection, "session_meta", "dependencia_assigned_at", "TEXT")
        # NULL mientras el asesor de la dependencia asignada no ha respondido
        # todavía -- se limpia en cada reasignación y se fija con el primer
        # mensaje de asesor después de esa asignación (ver add_admin_message
        # y find_unattended_sessions).
        _ensure_column(_connection, "session_meta", "first_response_at", "TEXT")

        # NULL en dependencia_id = documento general/compartido. Vive aparte
        # del índice FAISS a propósito: run_ingestion(rebuild=True) borra y
        # reconstruye el índice completo en cada ingesta, así que esta
        # etiqueta se perdería si viviera solo en los metadatos del índice.
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_dependencias (
                filename TEXT PRIMARY KEY,
                dependencia_id INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )

        # Propuestas de preguntas frecuentes generadas automáticamente al
        # resolver una conversación escalada (ver
        # app/services/faq_service.py). status: 'pending' | 'accepted' | 'rejected'.
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS faq_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                dependencia_id INTEGER,
                original_question TEXT NOT NULL,
                original_answer TEXT NOT NULL,
                suggested_question TEXT NOT NULL,
                suggested_answer TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
            """
        )
        _connection.execute("CREATE INDEX IF NOT EXISTS idx_faq_candidates_status ON faq_candidates(status)")

        # Métricas de cada respuesta generada por el bot (para el dashboard
        # de actividad -- ver app/services/dashboard_service.py). Se registra
        # desde app/services/chat_service.py::_draft_response.
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                retrieval_ms REAL NOT NULL,
                generation_ms REAL NOT NULL,
                total_ms REAL NOT NULL,
                chunks_retrieved INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _connection.execute("CREATE INDEX IF NOT EXISTS idx_chat_metrics_created ON chat_metrics(created_at)")

        # Registro histórico de cada llamada a la API de Groq (distinto del
        # limitador de tasa en app/rag/rate_limiter.py, que solo vive en
        # memoria) -- se registra desde app/rag/llm.py::_create_completion,
        # único punto de salida hacia Groq en todo el proyecto.
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS groq_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purpose TEXT NOT NULL,
                success INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _connection.execute("CREATE INDEX IF NOT EXISTS idx_groq_calls_created ON groq_calls(created_at)")

        _connection.commit()
    return _connection


def get_connection() -> sqlite3.Connection:
    """Punto de acceso público a la conexión SQLite compartida, para que
    app/services/admin_service.py (administración: dependencias, admins,
    sesiones, institución) la reutilice sin duplicar la inicialización del
    esquema ni el manejo de la conexión."""
    return _get_connection()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Versión pública de _ensure_column, para migraciones idempotentes
    hechas desde otros módulos que comparten esta misma conexión."""
    _ensure_column(conn, table, column, coltype)


def db_lock() -> threading.Lock:
    """El lock compartido de la conexión SQLite, para que otros módulos
    (admin_service.py) serialicen sus propias escrituras igual que lo hace
    este módulo."""
    return _lock


def get_history(session_id: str) -> List[Tuple[str, str]]:
    """Últimos MAX_HISTORY_TURNS turnos de la sesión, en orden cronológico
    (el más antiguo primero), para construir el prompt del LLM."""
    with _lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT question, answer FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, settings.MAX_HISTORY_TURNS),
        ).fetchall()
    return [(q, a) for q, a in reversed(rows)]


def append_turn(session_id: str, question: str, answer: str) -> str:
    """Guarda el turno y devuelve su timestamp (ISO 8601), para que el
    llamador pueda transmitirlo al panel de control en tiempo real con el
    mismo valor exacto que quedó persistido."""
    created_at = _now()
    with _lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO turns (session_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
            (session_id, question, answer, created_at),
        )
        conn.commit()
    return created_at


def clear_session(session_id: str) -> None:
    with _lock:
        conn = _get_connection()
        conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        conn.commit()


def needs_human(session_id: str) -> bool:
    """True si esta sesión está escalada a un asesor humano y aún no se ha
    marcado como resuelta -- el chatbot no debe responder mientras tanto."""
    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT needs_human FROM session_meta WHERE session_id = ?", (session_id,)
        ).fetchone()
    return bool(row and row[0])


def get_session_meta(session_id: str) -> dict:
    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT needs_human, student_name, student_email, dependencia_id FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return {"needs_human": False, "student_name": None, "student_email": None, "dependencia_id": None}
    needs_human_flag, student_name, student_email, dependencia_id = row
    return {
        "needs_human": bool(needs_human_flag),
        "student_name": student_name,
        "student_email": student_email,
        "dependencia_id": dependencia_id,
    }


def escalate_session(
    session_id: str, student_name: str, student_email: str, dependencia_id: Optional[int] = None
) -> str:
    """Marca la sesión como necesitando atención humana y guarda los datos
    de contacto del estudiante. dependencia_id (decidido por el LLM al
    momento de escalar, ver classify_department en app/rag/llm.py) es None
    cuando no se pudo clasificar -- la conversación queda en la bandeja del
    administrador general. Devuelve el timestamp del escalamiento."""
    escalated_at = _now()
    with _lock:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO session_meta
                (session_id, needs_human, student_name, student_email, escalated_at, resolved_at,
                 dependencia_id, dependencia_assigned_at, first_response_at)
            VALUES (?, 1, ?, ?, ?, NULL, ?, ?, NULL)
            ON CONFLICT(session_id) DO UPDATE SET
                needs_human = 1,
                student_name = excluded.student_name,
                student_email = excluded.student_email,
                escalated_at = excluded.escalated_at,
                resolved_at = NULL,
                dependencia_id = excluded.dependencia_id,
                dependencia_assigned_at = excluded.dependencia_assigned_at,
                first_response_at = NULL
            """,
            (session_id, student_name, student_email, escalated_at, dependencia_id, escalated_at),
        )
        conn.commit()
    return escalated_at


def reassign_dependencia(session_id: str, dependencia_id: Optional[int]) -> str:
    """Reasigna una conversación ya escalada a otra dependencia (o al
    administrador general, si dependencia_id es None) -- por redirección
    manual de un administrador, o automáticamente si nadie respondió a
    tiempo (ver find_unattended_sessions). Reinicia el cronómetro de
    atención: first_response_at vuelve a NULL, así que la nueva dependencia
    tiene sus propios 5 minutos. Funciona incluso si la sesión nunca tuvo
    fila en session_meta (poco probable en la práctica, ya que solo se
    reasigna algo que ya se ve en el panel, es decir, ya escalado)."""
    assigned_at = _now()
    with _lock:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO session_meta (session_id, needs_human, dependencia_id, dependencia_assigned_at, first_response_at)
            VALUES (?, 0, ?, ?, NULL)
            ON CONFLICT(session_id) DO UPDATE SET
                dependencia_id = excluded.dependencia_id,
                dependencia_assigned_at = excluded.dependencia_assigned_at,
                first_response_at = NULL
            """,
            (session_id, dependencia_id, assigned_at),
        )
        conn.commit()
    return assigned_at


def resolve_session(session_id: str, resolved_by: str) -> str:
    """Marca la sesión como solucionada y quita la marca de 'necesita
    atención humana' -- el chatbot vuelve a responder normalmente. Funciona
    tanto para sesiones ya escaladas como para sesiones sin escalar (el
    estudiante puede marcar como solucionada una conversación que nunca
    necesitó un asesor). resolved_by es 'student' o 'advisor', para poder
    hacerle seguimiento a quién cerró cada conversación."""
    resolved_at = _now()
    with _lock:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO session_meta (session_id, needs_human, resolved_at, resolved_by)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                needs_human = 0,
                resolved_at = excluded.resolved_at,
                resolved_by = excluded.resolved_by
            """,
            (session_id, resolved_at, resolved_by),
        )
        conn.commit()
    return resolved_at


def add_admin_message(session_id: str, sender: str, message: str, message_type: str = "text") -> str:
    """Guarda un mensaje intercambiado tras el escalamiento. sender es
    'student' o 'advisor'. message_type es 'text' salvo para el chequeo
    "¿Te puedo ayudar con algo más?" ('checkin') y la respuesta del
    estudiante a ese chequeo ('checkin_response'). Devuelve el timestamp
    guardado.

    Si sender es 'advisor', además marca first_response_at (solo la
    primera vez desde la asignación actual, ver escalate_session/
    reassign_dependencia) -- es la señal de "ya fue atendido" que usa
    find_unattended_sessions para no auto-redirigir algo que ya tiene
    respuesta."""
    created_at = _now()
    with _lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO admin_messages (session_id, sender, message, created_at, message_type) VALUES (?, ?, ?, ?, ?)",
            (session_id, sender, message, created_at, message_type),
        )
        if sender == "advisor":
            conn.execute(
                "UPDATE session_meta SET first_response_at = COALESCE(first_response_at, ?) WHERE session_id = ?",
                (created_at, session_id),
            )
        conn.commit()
    return created_at


def record_chat_metrics(
    session_id: str, retrieval_ms: float, generation_ms: float, total_ms: float, chunks_retrieved: int
) -> None:
    """Registra las métricas de una respuesta generada por el bot, para el
    dashboard de actividad (ver app/services/dashboard_service.py)."""
    with _lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO chat_metrics (session_id, retrieval_ms, generation_ms, total_ms, chunks_retrieved, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, retrieval_ms, generation_ms, total_ms, chunks_retrieved, _now()),
        )
        conn.commit()


def record_groq_call(purpose: str, success: bool) -> None:
    """Registra una llamada a la API de Groq, para el dashboard de
    actividad (uso histórico -- distinto del limitador de tasa en memoria
    de app/rag/rate_limiter.py)."""
    with _lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO groq_calls (purpose, success, created_at) VALUES (?, ?, ?)",
            (purpose, 1 if success else 0, _now()),
        )
        conn.commit()


_UNSCOPED = object()


def list_sessions(
    offset: int = 0,
    limit: int = 30,
    needs_human_only: bool = False,
    dependencia_scope=_UNSCOPED,
    general_oversight: bool = False,
) -> dict:
    """Conversaciones (sesiones), más recientes primero, con vista previa
    del último mensaje y si necesitan atención humana -- usado por el panel
    de control. La lista completa se arma y ordena en memoria (barato aun
    con miles de sesiones) y luego se pagina o filtra en Python, ya que
    viene de combinar dos tablas (turns y admin_messages) sin una relación
    1 a 1 sencilla de expresar en una sola consulta SQL paginada.

    dependencia_scope restringe a conversaciones que llegaron a escalarse
    (escalated_at no nulo) Y cuyo dependencia_id coincide -- None significa
    la bandeja del administrador general (escaladas sin dependencia
    asignada). Por defecto (_UNSCOPED) no se aplica ninguna restricción; la
    API siempre pasa el scope derivado de la identidad del administrador
    autenticado (nunca "sin restricción" en producción -- eso solo tendría
    sentido para uso interno).

    general_oversight=True (solo lo usa el rol 'general') reemplaza el
    filtro por dependencia_scope: en vez de solo las suyas, ve TODAS las
    conversaciones escaladas sin importar a qué dependencia estén
    asignadas -- es supervisor de todo el sistema, no solo de su propia
    bandeja.

    Devuelve un dict con:
    - sessions: la página pedida (o, si needs_human_only, TODAS las
      pendientes sin paginar -- se asume que son pocas).
    - total: conteo total de sesiones (para el encabezado del panel).
    - has_more: si quedan más sesiones después de esta página.
    - pending_count: conteo total de sesiones pendientes, sin importar la
      página actual (para que el chip de "pendientes" nunca quede corto).
    """
    all_sessions = _list_all_sessions()

    if general_oversight:
        all_sessions = [s for s in all_sessions if s["escalated_at"]]
    elif dependencia_scope is not _UNSCOPED:
        all_sessions = [
            s for s in all_sessions if s["escalated_at"] and s["dependencia_id"] == dependencia_scope
        ]

    total = len(all_sessions)
    pending_count = sum(1 for s in all_sessions if s["needs_human"])

    if needs_human_only:
        page = [s for s in all_sessions if s["needs_human"]]
        has_more = False
    else:
        page = all_sessions[offset : offset + limit]
        has_more = offset + limit < total

    return {"sessions": page, "total": total, "has_more": has_more, "pending_count": pending_count}


def _list_all_sessions() -> List[dict]:
    """Todas las conversaciones (sesiones) con al menos un turno, más
    recientes primero, con vista previa del último mensaje (de cualquiera
    de las dos tablas de actividad) y si necesitan atención humana."""
    with _lock:
        conn = _get_connection()
        turn_rows = conn.execute(
            """
            SELECT t.session_id, t.last_active, t.turn_count, last_turn.answer
            FROM (
                SELECT session_id, MAX(created_at) AS last_active, COUNT(*) AS turn_count, MAX(id) AS last_id
                FROM turns
                GROUP BY session_id
            ) t
            JOIN turns last_turn ON last_turn.id = t.last_id
            """
        ).fetchall()
        admin_rows = conn.execute(
            "SELECT session_id, message, MAX(created_at) AS last_active FROM admin_messages GROUP BY session_id"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT session_id, needs_human, student_name, student_email, escalated_at, dependencia_id, "
            "dependencia_assigned_at, first_response_at "
            "FROM session_meta"
        ).fetchall()

    sessions: dict = {}
    for session_id, last_active, turn_count, last_message in turn_rows:
        sessions[session_id] = {
            "session_id": session_id,
            "last_active": last_active,
            "turn_count": turn_count,
            "last_message": last_message,
        }

    for session_id, message, last_active in admin_rows:
        current = sessions.get(session_id)
        if current is None:
            sessions[session_id] = {
                "session_id": session_id,
                "last_active": last_active,
                "turn_count": 0,
                "last_message": message,
            }
        elif last_active > current["last_active"]:
            current["last_active"] = last_active
            current["last_message"] = message

    meta_map = {
        session_id: (bool(flag), student_name, student_email, escalated_at, dependencia_id, dep_assigned_at, first_response_at)
        for session_id, flag, student_name, student_email, escalated_at, dependencia_id, dep_assigned_at, first_response_at in meta_rows
    }
    for session_id, data in sessions.items():
        (
            needs_human_flag,
            student_name,
            student_email,
            escalated_at,
            dependencia_id,
            dependencia_assigned_at,
            first_response_at,
        ) = meta_map.get(session_id, (False, None, None, None, None, None, None))
        data["needs_human"] = needs_human_flag
        data["student_name"] = student_name
        data["student_email"] = student_email
        data["escalated_at"] = escalated_at
        data["dependencia_id"] = dependencia_id
        data["dependencia_assigned_at"] = dependencia_assigned_at
        data["first_response_at"] = first_response_at

    return sorted(sessions.values(), key=lambda s: s["last_active"], reverse=True)


def find_unattended_sessions(timeout_seconds: int) -> List[dict]:
    """Sesiones asignadas a una dependencia específica (no al general),
    todavía pendientes, sin ninguna respuesta de asesor desde esa
    asignación, y a las que ya se les venció el plazo -- candidatas a
    auto-redirigirse hacia el administrador general (ver
    app/main.py:_auto_escalation_loop). Cada resultado trae session_id y
    dependencia_id (la actual, para poder notificar a esa bandeja de que
    la conversación se le fue)."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=timeout_seconds)).isoformat()
    with _lock:
        conn = _get_connection()
        rows = conn.execute(
            """
            SELECT session_id, dependencia_id FROM session_meta
            WHERE needs_human = 1
              AND dependencia_id IS NOT NULL
              AND first_response_at IS NULL
              AND dependencia_assigned_at IS NOT NULL
              AND dependencia_assigned_at <= ?
            """,
            (cutoff,),
        ).fetchall()
    return [{"session_id": session_id, "dependencia_id": dependencia_id} for session_id, dependencia_id in rows]


def backup_now() -> Path:
    """Copia history.db a HISTORY_BACKUP_DIR con un nombre con marca de
    tiempo, usando la API de respaldo de SQLite (una copia consistente,
    segura de tomar aun con la base de datos en uso -- a diferencia de
    copiar el archivo directamente, que podría capturar una escritura a
    medias). Luego elimina los respaldos más viejos que excedan
    HISTORY_BACKUP_RETENTION. Devuelve la ruta del respaldo creado."""
    with _lock:
        conn = _get_connection()
        settings.HISTORY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest_path = settings.HISTORY_BACKUP_DIR / f"history-{timestamp}.db"
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            conn.backup(dest_conn)
        finally:
            dest_conn.close()

        backups = sorted(settings.HISTORY_BACKUP_DIR.glob("history-*.db"))
        excess = len(backups) - settings.HISTORY_BACKUP_RETENTION
        for old_backup in backups[: max(excess, 0)]:
            old_backup.unlink(missing_ok=True)

    return dest_path


def close() -> None:
    """Cierra la conexión SQLite. Usado por la suite de pruebas para poder
    borrar el archivo de base de datos de prueba al terminar (en Windows no
    se puede eliminar un archivo con una conexión abierta)."""
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None


def _decode_cursor(cursor: str) -> Tuple[str, Optional[int]]:
    created_at, sep, seq = cursor.rpartition("|")
    if sep and seq.isdigit():
        return created_at, int(seq)
    return cursor, None  # cursor sin "|" (no debería pasar, pero no revienta)


def _encode_cursor(message: dict) -> str:
    return f"{message['created_at']}|{message['_seq']}"


def get_history_page(session_id: str, before: Optional[str] = None, limit: int = 50) -> dict:
    """Página de la transcripción de una sesión, en orden cronológico
    ascendente (el más antiguo primero). Sin `before`, trae los últimos
    `limit` mensajes; con `before` (el cursor devuelto como `next_cursor`
    en la página anterior) trae los `limit` mensajes anteriores -- para
    "cargar mensajes anteriores" en el panel y en el chat del estudiante
    sin traer toda la conversación de una sola vez (un alumno puede
    acumular años de historial).

    El cursor combina created_at + una posición (`_seq`) en vez de usar
    solo la fecha: la pregunta y la respuesta de un mismo turno comparten
    exactamente el mismo created_at, y si el corte de página cae justo
    entre ambas, un cursor basado solo en la fecha perdería la que quedó
    del otro lado silenciosamente.

    La transcripción completa de la sesión se arma en memoria (barata: está
    acotada por los mensajes de esa única sesión, no de toda la base de
    datos) y luego se recorta -- misma estrategia que list_sessions()."""
    all_messages = _get_full_history_all(session_id)
    if before:
        cursor_created_at, cursor_seq = _decode_cursor(before)
        if cursor_seq is not None:
            all_messages = [m for m in all_messages if (m["created_at"], m["_seq"]) < (cursor_created_at, cursor_seq)]
        else:
            all_messages = [m for m in all_messages if m["created_at"] < cursor_created_at]

    has_more = len(all_messages) > limit
    page = all_messages[-limit:] if limit else all_messages
    next_cursor = _encode_cursor(page[0]) if page and has_more else None
    return {"messages": page, "has_more": has_more, "next_cursor": next_cursor}


def _get_full_history_all(session_id: str) -> List[dict]:
    """Transcripción completa de una sesión (turnos del bot + mensajes tras
    escalamiento), en orden cronológico. Cada mensaje lleva además un
    "_seq" (posición en el orden estable de inserción) para poder paginar
    sin ambigüedad cuando dos mensajes comparten el mismo created_at --
    ver get_history_page()."""
    with _lock:
        conn = _get_connection()
        turn_rows = conn.execute(
            "SELECT question, answer, created_at FROM turns WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        admin_rows = conn.execute(
            "SELECT sender, message, created_at, message_type FROM admin_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()

    messages: List[dict] = []
    for question, answer, created_at in turn_rows:
        messages.append({"sender": "student", "message": question, "created_at": created_at, "message_type": "text"})
        messages.append({"sender": "assistant", "message": answer, "created_at": created_at, "message_type": "text"})
    for sender, message, created_at, message_type in admin_rows:
        messages.append({"sender": sender, "message": message, "created_at": created_at, "message_type": message_type})

    for i, m in enumerate(messages):
        m["_seq"] = i
    messages.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return messages
