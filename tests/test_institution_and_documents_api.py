"""Pruebas HTTP de institución (nombre/logo dinámico) y documentos (subida,
listado, recategorización y borrado con etiqueta de dependencia).
embed_texts y vector_store se simulan para no cargar el modelo real de
embeddings ni tocar el índice FAISS real -- mismo patrón que
tests/test_ingest_service.py."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service

client = TestClient(app)

_counter = 0


def _fake_embed_texts(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


def _login_as(role="root", password="clave-segura-123"):
    global _counter
    _counter += 1
    username = f"test-inst-doc-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_institution_has_sensible_defaults_when_never_configured():
    res = client.get("/api/institution")

    assert res.status_code == 200
    body = res.json()
    assert body["name"]  # algún nombre por defecto, aunque nadie lo haya configurado
    assert body["logo_url"] is None


def test_update_institution_requires_root():
    token = _login_as(role="general")

    res = client.put(
        "/api/root/institution",
        data={"name": "Universidad Nueva", "extra_info": ""},
        headers=_auth(token),
    )

    assert res.status_code == 403


def test_update_institution_name_reflected_in_public_endpoint():
    token = _login_as()

    update_res = client.put(
        "/api/root/institution",
        data={"name": "Universidad de Prueba", "extra_info": "Contacto: test@uni.edu"},
        headers=_auth(token),
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Universidad de Prueba"

    public_res = client.get("/api/institution")
    assert public_res.json()["name"] == "Universidad de Prueba"
    assert public_res.json()["extra_info"] == "Contacto: test@uni.edu"


def test_document_upload_list_recategorize_and_delete(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)
    token = _login_as()

    dep = client.post(
        "/api/root/dependencias",
        json={"name": "Dep Documentos Test", "description": "desc"},
        headers=_auth(token),
    ).json()

    with (
        patch("app.services.ingest_service.embed_texts", side_effect=_fake_embed_texts),
        patch("app.services.ingest_service.vector_store.add_chunks"),
        patch("app.services.ingest_service.vector_store.reset_collection"),
    ):
        upload_res = client.post(
            "/api/root/documents",
            files={
                "file": (
                    "prueba.txt",
                    b"Contenido de prueba con suficiente longitud para generar un chunk.",
                    "text/plain",
                )
            },
            data={"dependencia_id": str(dep["id"])},
            headers=_auth(token),
        )
        assert upload_res.status_code == 200
        assert upload_res.json()["documents_processed"] == 1

        list_res = client.get("/api/root/documents", headers=_auth(token))
        assert list_res.status_code == 200
        docs = list_res.json()
        assert any(d["filename"] == "prueba.txt" and d["dependencia_id"] == dep["id"] for d in docs)

        recategorize_res = client.put(
            "/api/root/documents/prueba.txt", json={"dependencia_id": None}, headers=_auth(token)
        )
        assert recategorize_res.status_code == 200

        list_res_2 = client.get("/api/root/documents", headers=_auth(token))
        doc_after = next(d for d in list_res_2.json() if d["filename"] == "prueba.txt")
        assert doc_after["dependencia_id"] is None

        delete_res = client.delete("/api/root/documents/prueba.txt", headers=_auth(token))
        assert delete_res.status_code == 200
        assert not (tmp_path / "prueba.txt").exists()


def test_document_upload_rejects_disallowed_extension(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENTS_DIR", tmp_path)
    token = _login_as()

    res = client.post(
        "/api/root/documents",
        files={"file": ("prueba.exe", b"contenido", "application/octet-stream")},
        headers=_auth(token),
    )

    assert res.status_code == 400
