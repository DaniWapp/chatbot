"""Pruebas de los endpoints de administración de orígenes permitidos para
embeber /widget (app/services/widget_service.py): root y el administrador
general pueden gestionarla, dependencia no. También verifica que /widget
arma su cabecera CSP frame-ancestors dinámicamente a partir de esa lista."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service, widget_service

client = TestClient(app)

_counter = 0


def _login_as(role="root", password="clave-segura-123", dependencia_id=None):
    global _counter
    _counter += 1
    username = f"test-widget-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _origin():
    return f"https://api-test-{uuid.uuid4().hex[:8]}.edu.co"


def test_root_can_add_list_and_delete_origin():
    token = _login_as(role="root")
    origin = _origin()

    create_res = client.post("/api/root/widget-origins", json={"origin": origin}, headers=_auth(token))
    assert create_res.status_code == 200
    origin_id = create_res.json()["id"]
    assert create_res.json()["origin"] == origin

    list_res = client.get("/api/root/widget-origins", headers=_auth(token))
    assert any(o["origin"] == origin for o in list_res.json())

    delete_res = client.delete(f"/api/root/widget-origins/{origin_id}", headers=_auth(token))
    assert delete_res.status_code == 200
    list_after = client.get("/api/root/widget-origins", headers=_auth(token))
    assert not any(o["origin"] == origin for o in list_after.json())


def test_root_adding_malformed_origin_returns_409():
    token = _login_as(role="root")
    res = client.post("/api/root/widget-origins", json={"origin": "no-es-una-url"}, headers=_auth(token))
    assert res.status_code == 409


def test_root_adding_duplicate_origin_returns_409():
    token = _login_as(role="root")
    origin = _origin()
    client.post("/api/root/widget-origins", json={"origin": origin}, headers=_auth(token))

    res = client.post("/api/root/widget-origins", json={"origin": origin}, headers=_auth(token))
    assert res.status_code == 409


def test_general_admin_can_manage_origins_via_panel():
    token = _login_as(role="general")
    origin = _origin()

    create_res = client.post("/api/admin/widget-origins", json={"origin": origin}, headers=_auth(token))
    assert create_res.status_code == 200
    origin_id = create_res.json()["id"]

    list_res = client.get("/api/admin/widget-origins", headers=_auth(token))
    assert list_res.status_code == 200
    assert any(o["origin"] == origin for o in list_res.json())

    delete_res = client.delete(f"/api/admin/widget-origins/{origin_id}", headers=_auth(token))
    assert delete_res.status_code == 200


def test_dependencia_admin_cannot_manage_origins():
    root_token = _login_as(role="root")
    dep = client.post(
        "/api/root/dependencias", json={"name": "Dep Widget Test", "description": "desc"}, headers=_auth(root_token)
    ).json()
    dep_token = _login_as(role="dependencia", dependencia_id=dep["id"])

    assert client.get("/api/admin/widget-origins", headers=_auth(dep_token)).status_code == 403
    assert client.post(
        "/api/admin/widget-origins", json={"origin": _origin()}, headers=_auth(dep_token)
    ).status_code == 403
    assert client.delete("/api/admin/widget-origins/1", headers=_auth(dep_token)).status_code == 403


def test_widget_page_denies_framing_by_default():
    for o in widget_service.list_origins():
        widget_service.remove_origin(o["id"])

    res = client.get("/widget")
    assert res.status_code == 200
    assert res.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_widget_page_allows_configured_origins():
    origin = _origin()
    widget_service.add_origin(origin)

    res = client.get("/widget")

    assert origin in res.headers["content-security-policy"]
