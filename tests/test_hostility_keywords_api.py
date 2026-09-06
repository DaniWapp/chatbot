"""Pruebas de los endpoints de administración de la lista de palabras del
detector de hostilidad (app/services/hostility_service.py): root y el
administrador general pueden gestionarla, dependencia no."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service

client = TestClient(app)

_counter = 0


def _login_as(role="root", password="clave-segura-123", dependencia_id=None):
    global _counter
    _counter += 1
    username = f"test-hostility-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _phrase():
    return f"zzz-api-test-{uuid.uuid4().hex[:6]}"


def test_root_can_add_list_and_delete_keyword():
    token = _login_as(role="root")
    phrase = _phrase()

    create_res = client.post("/api/root/hostility-keywords", json={"phrase": phrase}, headers=_auth(token))
    assert create_res.status_code == 200
    keyword_id = create_res.json()["id"]

    list_res = client.get("/api/root/hostility-keywords", headers=_auth(token))
    assert any(k["phrase"] == phrase for k in list_res.json())

    delete_res = client.delete(f"/api/root/hostility-keywords/{keyword_id}", headers=_auth(token))
    assert delete_res.status_code == 200
    list_after = client.get("/api/root/hostility-keywords", headers=_auth(token))
    assert not any(k["phrase"] == phrase for k in list_after.json())


def test_root_adding_duplicate_keyword_returns_409():
    token = _login_as(role="root")
    phrase = _phrase()
    client.post("/api/root/hostility-keywords", json={"phrase": phrase}, headers=_auth(token))

    res = client.post("/api/root/hostility-keywords", json={"phrase": phrase}, headers=_auth(token))
    assert res.status_code == 409


def test_general_admin_can_manage_keywords_via_panel():
    token = _login_as(role="general")
    phrase = _phrase()

    create_res = client.post("/api/admin/hostility-keywords", json={"phrase": phrase}, headers=_auth(token))
    assert create_res.status_code == 200
    keyword_id = create_res.json()["id"]

    list_res = client.get("/api/admin/hostility-keywords", headers=_auth(token))
    assert list_res.status_code == 200
    assert any(k["phrase"] == phrase for k in list_res.json())

    delete_res = client.delete(f"/api/admin/hostility-keywords/{keyword_id}", headers=_auth(token))
    assert delete_res.status_code == 200


def test_dependencia_admin_cannot_manage_keywords():
    root_token = _login_as(role="root")
    dep = client.post(
        "/api/root/dependencias", json={"name": "Dep Hostility Test", "description": "desc"}, headers=_auth(root_token)
    ).json()
    dep_token = _login_as(role="dependencia", dependencia_id=dep["id"])

    assert client.get("/api/admin/hostility-keywords", headers=_auth(dep_token)).status_code == 403
    assert client.post(
        "/api/admin/hostility-keywords", json={"phrase": _phrase()}, headers=_auth(dep_token)
    ).status_code == 403
    assert client.delete("/api/admin/hostility-keywords/1", headers=_auth(dep_token)).status_code == 403
