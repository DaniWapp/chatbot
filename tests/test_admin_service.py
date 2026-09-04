"""Pruebas del servicio de administración (app/services/admin_service.py):
hash de contraseñas, validaciones al crear/editar administradores, sesiones
de login (creación, expiración, invalidación al cambiar contraseña o
desactivar la cuenta) y el CRUD de dependencias."""
import pytest

from app.services import admin_service as svc


def test_password_hash_roundtrip():
    hashed = svc.hash_password("mi-clave-123")
    assert svc.verify_password("mi-clave-123", hashed) is True
    assert svc.verify_password("otra-clave", hashed) is False


def test_create_admin_rejects_invalid_role():
    with pytest.raises(ValueError):
        svc.create_admin("svc-bad-role", "clave123", "Nombre", "supervisor")


def test_create_admin_dependencia_role_requires_dependencia_id():
    with pytest.raises(ValueError):
        svc.create_admin("svc-dep-missing", "clave123", "Nombre", "dependencia")


def test_create_admin_non_dependencia_role_rejects_dependencia_id():
    dep_id = svc.create_dependencia("Dep Test A", "descripcion")
    with pytest.raises(ValueError):
        svc.create_admin("svc-general-with-dep", "clave123", "Nombre", "general", dependencia_id=dep_id)


def test_create_admin_rejects_duplicate_username():
    svc.create_admin("svc-dup-user", "clave123", "Nombre", "general")
    with pytest.raises(ValueError):
        svc.create_admin("svc-dup-user", "otra-clave", "Otro Nombre", "general")


def test_authenticate_success_and_failure():
    svc.create_admin("svc-auth-user", "clave-correcta", "Nombre", "general")

    assert svc.authenticate("svc-auth-user", "clave-correcta") is not None
    assert svc.authenticate("svc-auth-user", "clave-incorrecta") is None
    assert svc.authenticate("svc-no-existe", "cualquier-cosa") is None


def test_authenticate_rejects_inactive_account():
    admin_id = svc.create_admin("svc-inactive-user", "clave123", "Nombre", "general")
    svc.set_admin_active(admin_id, False)

    assert svc.authenticate("svc-inactive-user", "clave123") is None


def test_session_roundtrip_for_dependencia_admin():
    dep_id = svc.create_dependencia("Dep Test B", "descripcion")
    admin_id = svc.create_admin("svc-dep-admin", "clave123", "Nombre Dep", "dependencia", dependencia_id=dep_id)

    token = svc.create_session(admin_id)
    identity = svc.get_identity_from_token(token)

    assert identity is not None
    assert identity["role"] == "dependencia"
    assert identity["dependencia_id"] == dep_id


def test_expired_session_is_rejected_and_removed():
    admin_id = svc.create_admin("svc-expired-user", "clave123", "Nombre", "general")
    token = svc.create_session(admin_id, ttl_seconds=-1)  # ya expirado al crearlo

    assert svc.get_identity_from_token(token) is None
    # y la fila quedó eliminada, no solo ignorada
    with svc.history.db_lock():
        conn = svc.history.get_connection()
        row = conn.execute("SELECT 1 FROM admin_sessions WHERE token = ?", (token,)).fetchone()
    assert row is None


def test_changing_password_invalidates_existing_sessions():
    admin_id = svc.create_admin("svc-pwchange-user", "clave-vieja", "Nombre", "general")
    token = svc.create_session(admin_id)
    assert svc.get_identity_from_token(token) is not None

    svc.set_admin_password(admin_id, "clave-nueva")

    assert svc.get_identity_from_token(token) is None
    assert svc.authenticate("svc-pwchange-user", "clave-nueva") is not None


def test_deactivating_admin_invalidates_existing_sessions():
    admin_id = svc.create_admin("svc-deactivate-user", "clave123", "Nombre", "general")
    token = svc.create_session(admin_id)

    svc.set_admin_active(admin_id, False)

    assert svc.get_identity_from_token(token) is None


def test_dependencia_crud():
    dep_id = svc.create_dependencia("Bienestar Universitario", "Becas, salud, deporte")
    assert any(d["id"] == dep_id for d in svc.list_dependencias())

    svc.update_dependencia(dep_id, description="Becas, salud, deporte y cultura")
    assert svc.get_dependencia(dep_id)["description"] == "Becas, salud, deporte y cultura"

    svc.delete_dependencia(dep_id)
    assert svc.get_dependencia(dep_id) is None


def test_delete_dependencia_blocked_while_admin_assigned():
    dep_id = svc.create_dependencia("Dep Con Admin", "descripcion")
    svc.create_admin("svc-dep-blocker", "clave123", "Nombre", "dependencia", dependencia_id=dep_id)

    with pytest.raises(ValueError):
        svc.delete_dependencia(dep_id)
