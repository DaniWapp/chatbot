"""Pruebas de los endpoints de horario de atención por dependencia
(app/services/admin_service.py::set_dependencia_horario): root y el
administrador general pueden gestionar el de cualquier dependencia; una
dependencia puede gestionar la suya propia, pero no la de otra."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service

client = TestClient(app)

_counter = 0


def _login_as(role="root", password="clave-segura-123", dependencia_id=None):
    global _counter
    _counter += 1
    username = f"test-horario-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_dependencia(root_token):
    name = f"Dep Horario Test {uuid.uuid4().hex[:6]}"
    res = client.post("/api/root/dependencias", json={"name": name, "description": "desc"}, headers=_auth(root_token))
    return res.json()["id"]


_HORARIO_PAYLOAD = {"dias": [1, 2, 3, 4, 5], "rangos": [{"inicio": "08:00", "fin": "12:00"}, {"inicio": "14:00", "fin": "18:00"}]}


def test_root_can_set_horario_for_any_dependencia():
    root_token = _login_as(role="root")
    dep_id = _create_dependencia(root_token)

    res = client.put(f"/api/root/dependencias/{dep_id}/horario", json=_HORARIO_PAYLOAD, headers=_auth(root_token))

    assert res.status_code == 200
    assert res.json()["horario_dias"] == [1, 2, 3, 4, 5]
    assert res.json()["horario_rangos"] == [["08:00", "12:00"], ["14:00", "18:00"]]


def test_general_can_set_horario_for_any_dependencia_via_panel():
    root_token = _login_as(role="root")
    dep_id = _create_dependencia(root_token)
    general_token = _login_as(role="general")

    res = client.put(
        f"/api/admin/dependencias/{dep_id}/horario", json=_HORARIO_PAYLOAD, headers=_auth(general_token)
    )

    assert res.status_code == 200
    assert res.json()["horario_dias"] == [1, 2, 3, 4, 5]


def test_dependencia_can_set_its_own_horario():
    root_token = _login_as(role="root")
    dep_id = _create_dependencia(root_token)
    dep_token = _login_as(role="dependencia", dependencia_id=dep_id)

    res = client.put(f"/api/admin/dependencias/{dep_id}/horario", json=_HORARIO_PAYLOAD, headers=_auth(dep_token))

    assert res.status_code == 200


def test_dependencia_cannot_set_horario_of_another_dependencia():
    root_token = _login_as(role="root")
    dep_id = _create_dependencia(root_token)
    other_dep_id = _create_dependencia(root_token)
    dep_token = _login_as(role="dependencia", dependencia_id=dep_id)

    res = client.put(
        f"/api/admin/dependencias/{other_dep_id}/horario", json=_HORARIO_PAYLOAD, headers=_auth(dep_token)
    )

    assert res.status_code == 403


def test_horario_rejects_invalid_time_format():
    root_token = _login_as(role="root")
    dep_id = _create_dependencia(root_token)

    res = client.put(
        f"/api/root/dependencias/{dep_id}/horario",
        json={"dias": [1], "rangos": [{"inicio": "8am", "fin": "12pm"}]},
        headers=_auth(root_token),
    )

    assert res.status_code == 422


def test_horario_rejects_range_where_end_is_before_start():
    root_token = _login_as(role="root")
    dep_id = _create_dependencia(root_token)

    res = client.put(
        f"/api/root/dependencias/{dep_id}/horario",
        json={"dias": [1], "rangos": [{"inicio": "18:00", "fin": "08:00"}]},
        headers=_auth(root_token),
    )

    assert res.status_code == 422
