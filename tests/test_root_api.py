"""Pruebas HTTP de las rutas exclusivas de root: CRUD de dependencias,
CRUD de administradores, y cambio de contraseña propia. Confirma también
que ninguna de estas rutas es accesible para un administrador que no sea
root."""
from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service

client = TestClient(app)

_counter = 0


def _login_as(role="root", dependencia_id=None, password="clave-segura-123"):
    global _counter
    _counter += 1
    username = f"test-root-api-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    data = res.json()
    return data["token"], username


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_root_routes_reject_non_root_admin():
    token, _ = _login_as(role="general")

    assert client.get("/api/root/dependencias", headers=_auth(token)).status_code == 403
    assert client.get("/api/root/admins", headers=_auth(token)).status_code == 403
    assert (
        client.post(
            "/api/root/dependencias", json={"name": "X", "description": "Y"}, headers=_auth(token)
        ).status_code
        == 403
    )


def test_dependencia_crud_via_api():
    token, _ = _login_as()

    create_res = client.post(
        "/api/root/dependencias",
        json={"name": "Registro Académico", "description": "Matrículas, certificados, notas"},
        headers=_auth(token),
    )
    assert create_res.status_code == 200
    dep = create_res.json()
    assert dep["name"] == "Registro Académico"

    list_res = client.get("/api/root/dependencias", headers=_auth(token))
    assert any(d["id"] == dep["id"] for d in list_res.json())

    update_res = client.put(
        f"/api/root/dependencias/{dep['id']}",
        json={"description": "Matrículas, certificados, notas y grados"},
        headers=_auth(token),
    )
    assert update_res.status_code == 200
    assert update_res.json()["description"] == "Matrículas, certificados, notas y grados"

    delete_res = client.delete(f"/api/root/dependencias/{dep['id']}", headers=_auth(token))
    assert delete_res.status_code == 200


def test_dependencia_delete_blocked_while_admin_assigned_via_api():
    token, _ = _login_as()
    dep = client.post(
        "/api/root/dependencias", json={"name": "Dep Bloqueada", "description": "desc"}, headers=_auth(token)
    ).json()
    client.post(
        "/api/root/admins",
        json={
            "username": f"dep-admin-{dep['id']}@nubecol.com",
            "password": "clave-segura-123",
            "display_name": "Admin Dep",
            "role": "dependencia",
            "dependencia_id": dep["id"],
        },
        headers=_auth(token),
    )

    delete_res = client.delete(f"/api/root/dependencias/{dep['id']}", headers=_auth(token))

    assert delete_res.status_code == 409


def test_admin_crud_via_api():
    token, _ = _login_as()

    create_res = client.post(
        "/api/root/admins",
        json={
            "username": "test-crud-admin@nubecol.com",
            "password": "clave-segura-123",
            "display_name": "Nuevo Admin",
            "role": "general",
        },
        headers=_auth(token),
    )
    assert create_res.status_code == 200
    admin = create_res.json()
    assert "password_hash" not in admin
    assert admin["active"] is True

    update_res = client.put(
        f"/api/root/admins/{admin['id']}", json={"display_name": "Admin Renombrado"}, headers=_auth(token)
    )
    assert update_res.status_code == 200
    assert update_res.json()["display_name"] == "Admin Renombrado"

    password_res = client.post(
        f"/api/root/admins/{admin['id']}/set-password", json={"password": "otra-clave-1234"}, headers=_auth(token)
    )
    assert password_res.status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "test-crud-admin@nubecol.com", "password": "otra-clave-1234"}
    ).status_code == 200

    deactivate_res = client.post(
        f"/api/root/admins/{admin['id']}/set-active", json={"active": False}, headers=_auth(token)
    )
    assert deactivate_res.status_code == 200
    assert (
        client.post(
            "/api/auth/login", json={"username": "test-crud-admin@nubecol.com", "password": "otra-clave-1234"}
        ).status_code
        == 401
    )


def test_admin_create_rejects_invalid_dependencia_combo():
    token, _ = _login_as()

    res = client.post(
        "/api/root/admins",
        json={
            "username": "test-bad-combo@nubecol.com",
            "password": "clave-segura-123",
            "display_name": "Bad Combo",
            "role": "dependencia",
        },
        headers=_auth(token),
    )

    assert res.status_code == 400


def test_change_own_password():
    token, username = _login_as(role="general", password="clave-original-1")

    wrong_res = client.post(
        "/api/auth/change-password",
        json={"current_password": "clave-incorrecta", "new_password": "nueva-clave-2"},
        headers=_auth(token),
    )
    assert wrong_res.status_code == 401

    ok_res = client.post(
        "/api/auth/change-password",
        json={"current_password": "clave-original-1", "new_password": "nueva-clave-2"},
        headers=_auth(token),
    )
    assert ok_res.status_code == 200

    # Cambiar la contraseña invalida la sesión actual, incluida la que se usó para el cambio.
    assert client.get("/api/root/dependencias", headers=_auth(token)).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": username, "password": "nueva-clave-2"}
    ).status_code == 200
