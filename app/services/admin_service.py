"""Cuentas de administrador (root, general, dependencia), sesiones de login
y dependencias (departamentos). Comparte la única conexión SQLite de la app
(y su esquema, ya inicializado) con app/services/history.py, vía
history.get_connection()/ensure_column()/db_lock() -- ver el docstring de
ese módulo.
"""
import datetime
import secrets
from typing import List, Optional

import bcrypt

from app.services import history

VALID_ROLES = {"root", "general", "dependencia"}
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 días
DEFAULT_INSTITUTION_NAME = "Facultad de Ingeniería"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Hash corrupto o con un formato inesperado: tratarlo como no coincide.
        return False


# --- Administradores ---------------------------------------------------


def _row_to_admin(row) -> dict:
    admin_id, username, password_hash, display_name, role, dependencia_id, active, created_at = row
    return {
        "id": admin_id,
        "username": username,
        "password_hash": password_hash,
        "display_name": display_name,
        "role": role,
        "dependencia_id": dependencia_id,
        "active": bool(active),
        "created_at": created_at,
    }


def create_admin(
    username: str, password: str, display_name: str, role: str, dependencia_id: Optional[int] = None
) -> int:
    """Crea una cuenta de administrador. role es 'root', 'general' o
    'dependencia' (este último requiere dependencia_id). Lanza ValueError
    si el usuario ya existe, el rol no es válido, o falta/sobra
    dependencia_id según el rol."""
    if role not in VALID_ROLES:
        raise ValueError(f"Rol inválido: {role!r}")
    if role == "dependencia" and dependencia_id is None:
        raise ValueError("role='dependencia' requiere dependencia_id")
    if role != "dependencia" and dependencia_id is not None:
        raise ValueError("dependencia_id solo aplica a role='dependencia'")

    with history.db_lock():
        conn = history.get_connection()
        existing = conn.execute("SELECT 1 FROM admins WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError(f"El usuario '{username}' ya existe.")
        cursor = conn.execute(
            """
            INSERT INTO admins (username, password_hash, display_name, role, dependencia_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (username, hash_password(password), display_name, role, dependencia_id, _now()),
        )
        conn.commit()
        return cursor.lastrowid


def get_admin_by_username(username: str) -> Optional[dict]:
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            "SELECT id, username, password_hash, display_name, role, dependencia_id, active, created_at "
            "FROM admins WHERE username = ?",
            (username,),
        ).fetchone()
    return _row_to_admin(row) if row else None


def get_admin_by_id(admin_id: int) -> Optional[dict]:
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            "SELECT id, username, password_hash, display_name, role, dependencia_id, active, created_at "
            "FROM admins WHERE id = ?",
            (admin_id,),
        ).fetchone()
    return _row_to_admin(row) if row else None


def list_admins() -> List[dict]:
    """Todos los administradores (activos e inactivos) -- el panel de root
    decide cómo mostrarlos."""
    with history.db_lock():
        conn = history.get_connection()
        rows = conn.execute(
            "SELECT id, username, password_hash, display_name, role, dependencia_id, active, created_at "
            "FROM admins ORDER BY created_at ASC"
        ).fetchall()
    return [_row_to_admin(row) for row in rows]


def update_admin(
    admin_id: int,
    display_name: Optional[str] = None,
    role: Optional[str] = None,
    dependencia_id: Optional[int] = None,
) -> None:
    """Actualiza los campos dados (los que sean None no se tocan, salvo que
    se pase explícitamente role='dependencia' con dependencia_id, o un rol
    distinto -- en cuyo caso dependencia_id se limpia)."""
    current = get_admin_by_id(admin_id)
    if current is None:
        raise ValueError(f"No existe el administrador {admin_id}")

    new_role = role if role is not None else current["role"]
    if new_role not in VALID_ROLES:
        raise ValueError(f"Rol inválido: {new_role!r}")
    if new_role == "dependencia":
        new_dependencia_id = dependencia_id if dependencia_id is not None else current["dependencia_id"]
        if new_dependencia_id is None:
            raise ValueError("role='dependencia' requiere dependencia_id")
    else:
        new_dependencia_id = None

    new_display_name = display_name if display_name is not None else current["display_name"]

    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "UPDATE admins SET display_name = ?, role = ?, dependencia_id = ? WHERE id = ?",
            (new_display_name, new_role, new_dependencia_id, admin_id),
        )
        conn.commit()


def set_admin_password(admin_id: int, new_password: str) -> None:
    """Cambia la contraseña e invalida todas las sesiones activas de ese
    administrador (debe volver a loguearse)."""
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "UPDATE admins SET password_hash = ? WHERE id = ?", (hash_password(new_password), admin_id)
        )
        conn.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (admin_id,))
        conn.commit()


def set_admin_active(admin_id: int, active: bool) -> None:
    """Activa/desactiva una cuenta. Desactivar es el equivalente a
    "eliminar" en el CRUD del root -- se conserva la fila para no romper la
    trazabilidad histórica (resolved_by, reasignaciones, etc.) y se
    invalidan sus sesiones activas."""
    with history.db_lock():
        conn = history.get_connection()
        conn.execute("UPDATE admins SET active = ? WHERE id = ?", (1 if active else 0, admin_id))
        if not active:
            conn.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (admin_id,))
        conn.commit()


def authenticate(username: str, password: str) -> Optional[dict]:
    """Verifica usuario/contraseña. Devuelve el admin (sin password_hash
    incluido implícitamente en el uso normal, el llamador decide) solo si
    existe, está activo y la contraseña coincide; None en cualquier otro
    caso (mensaje de error genérico en la capa HTTP, para no filtrar cuál
    de los dos motivos fue)."""
    admin = get_admin_by_username(username)
    if admin is None or not admin["active"]:
        return None
    if not verify_password(password, admin["password_hash"]):
        return None
    return admin


# --- Sesiones ------------------------------------------------------------


def create_session(admin_id: int, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = (now + datetime.timedelta(seconds=ttl_seconds)).isoformat()
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "INSERT INTO admin_sessions (token, admin_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, admin_id, now.isoformat(), expires_at),
        )
        conn.commit()
    return token


def get_identity_from_token(token: str) -> Optional[dict]:
    """Resuelve un token de sesión a la identidad del administrador (id,
    username, display_name, role, dependencia_id). None si el token no
    existe, expiró, o la cuenta fue desactivada mientras tanto."""
    if not token:
        return None
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            """
            SELECT a.id, a.username, a.display_name, a.role, a.dependencia_id, a.active, s.expires_at
            FROM admin_sessions s
            JOIN admins a ON a.id = s.admin_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    if row is None:
        return None
    admin_id, username, display_name, role, dependencia_id, active, expires_at = row
    if not active:
        return None
    if expires_at < _now():
        delete_session(token)
        return None
    return {
        "id": admin_id,
        "username": username,
        "display_name": display_name,
        "role": role,
        "dependencia_id": dependencia_id,
    }


def delete_session(token: str) -> None:
    with history.db_lock():
        conn = history.get_connection()
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
        conn.commit()


# --- Dependencias ----------------------------------------------------------


def create_dependencia(name: str, description: str) -> int:
    with history.db_lock():
        conn = history.get_connection()
        cursor = conn.execute(
            "INSERT INTO dependencias (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, _now()),
        )
        conn.commit()
        return cursor.lastrowid


def list_dependencias() -> List[dict]:
    with history.db_lock():
        conn = history.get_connection()
        rows = conn.execute("SELECT id, name, description, created_at FROM dependencias ORDER BY name ASC").fetchall()
    return [{"id": r[0], "name": r[1], "description": r[2], "created_at": r[3]} for r in rows]


def get_dependencia(dependencia_id: int) -> Optional[dict]:
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            "SELECT id, name, description, created_at FROM dependencias WHERE id = ?", (dependencia_id,)
        ).fetchone()
    return {"id": row[0], "name": row[1], "description": row[2], "created_at": row[3]} if row else None


def update_dependencia(dependencia_id: int, name: Optional[str] = None, description: Optional[str] = None) -> None:
    current = get_dependencia(dependencia_id)
    if current is None:
        raise ValueError(f"No existe la dependencia {dependencia_id}")
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            "UPDATE dependencias SET name = ?, description = ? WHERE id = ?",
            (name if name is not None else current["name"], description if description is not None else current["description"], dependencia_id),
        )
        conn.commit()


def delete_dependencia(dependencia_id: int) -> None:
    """Elimina una dependencia. Se rechaza si todavía tiene administradores
    activos asignados, para no dejar cuentas con un dependencia_id
    huérfano."""
    with history.db_lock():
        conn = history.get_connection()
        still_assigned = conn.execute(
            "SELECT COUNT(*) FROM admins WHERE dependencia_id = ? AND active = 1", (dependencia_id,)
        ).fetchone()[0]
        if still_assigned:
            raise ValueError(
                "No se puede eliminar: todavía hay administradores activos asignados a esta dependencia."
            )
        conn.execute("DELETE FROM dependencias WHERE id = ?", (dependencia_id,))
        conn.commit()


# --- Institución -----------------------------------------------------


def get_institution() -> dict:
    """Nombre, logo e información extra de la institución. Si nunca se ha
    guardado nada (instalación nueva), devuelve el nombre por defecto que
    ya traía el proyecto -- para no cambiar el comportamiento visible hasta
    que el root lo edite explícitamente."""
    with history.db_lock():
        conn = history.get_connection()
        row = conn.execute(
            "SELECT name, logo_filename, extra_info FROM institution_settings WHERE id = 1"
        ).fetchone()
    if row is None:
        return {"name": DEFAULT_INSTITUTION_NAME, "logo_filename": None, "extra_info": None}
    return {"name": row[0], "logo_filename": row[1], "extra_info": row[2]}


def update_institution(
    name: str, extra_info: Optional[str] = None, logo_filename: Optional[str] = None
) -> dict:
    """Actualiza la institución (fila única, UPSERT). Si logo_filename es
    None, se conserva el logo ya guardado -- una actualización de solo
    texto no debe borrar el logo existente."""
    current = get_institution()
    final_logo = logo_filename if logo_filename is not None else current["logo_filename"]
    with history.db_lock():
        conn = history.get_connection()
        conn.execute(
            """
            INSERT INTO institution_settings (id, name, logo_filename, extra_info, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                logo_filename = excluded.logo_filename,
                extra_info = excluded.extra_info,
                updated_at = excluded.updated_at
            """,
            (name, final_logo, extra_info, _now()),
        )
        conn.commit()
    return get_institution()
