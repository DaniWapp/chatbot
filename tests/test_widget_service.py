"""Pruebas de app/services/widget_service.py: CRUD de orígenes permitidos
para embeber /widget, y normalización/validación de la URL guardada."""
import uuid

import pytest

from app.services import widget_service


def _origin() -> str:
    return f"https://sitio-de-prueba-{uuid.uuid4().hex[:8]}.edu.co"


def test_list_origins_does_not_include_unrelated_entries():
    origin = _origin()
    assert not any(o["origin"] == origin for o in widget_service.list_origins())


def test_add_list_and_remove_origin():
    origin = _origin()

    created = widget_service.add_origin(origin)
    assert created["origin"] == origin
    assert any(o["origin"] == origin for o in widget_service.list_origins())

    widget_service.remove_origin(created["id"])
    assert not any(o["origin"] == origin for o in widget_service.list_origins())


def test_add_origin_normalizes_full_url_down_to_its_origin():
    base = _origin()
    created = widget_service.add_origin(f"{base}/pagina/inicio?ref=x")

    assert created["origin"] == base


def test_add_origin_lowercases_scheme_and_host():
    base = _origin()
    created = widget_service.add_origin(base.upper())

    assert created["origin"] == base.lower()


def test_add_origin_rejects_missing_scheme():
    with pytest.raises(ValueError):
        widget_service.add_origin("sitio-de-prueba.edu.co")


def test_add_origin_rejects_non_http_scheme():
    with pytest.raises(ValueError):
        widget_service.add_origin("ftp://sitio-de-prueba.edu.co")


def test_add_origin_rejects_duplicate():
    origin = _origin()
    widget_service.add_origin(origin)

    with pytest.raises(ValueError):
        widget_service.add_origin(origin)


def test_remove_origin_on_missing_id_does_not_raise():
    widget_service.remove_origin(999999)
