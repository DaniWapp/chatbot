"""Pruebas HTTP de los endpoints de rastreo de sitios web
(/api/root/crawl-site). crawl_job_service se mockea en la mayoría --
solo confirma que la API arma bien el job y expone su estado, no repite
las pruebas de orquestación de tests/test_crawl_job_service.py."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import admin_service

client = TestClient(app)

_counter = 0


def _login_as(role="root", password="clave-segura-123", dependencia_id=None):
    global _counter
    _counter += 1
    username = f"test-crawl-{role}-{_counter}"
    admin_service.create_admin(username, password, f"Admin {role}", role, dependencia_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_crawl_site_requires_root():
    dep_id = admin_service.create_dependencia("Dep Crawl Auth", "")
    token = _login_as(role="dependencia", dependencia_id=dep_id)
    res = client.post(
        "/api/root/crawl-site",
        json={"seed_url": "https://sitio.edu/cucuta/"},
        headers=_auth(token),
    )
    assert res.status_code == 403


def test_crawl_site_rejects_non_http_seed_url():
    token = _login_as()
    res = client.post(
        "/api/root/crawl-site",
        json={"seed_url": "ftp://sitio.edu/cucuta/"},
        headers=_auth(token),
    )
    assert res.status_code == 422


def test_crawl_site_rejects_max_pages_over_limit():
    token = _login_as()
    res = client.post(
        "/api/root/crawl-site",
        json={"seed_url": "https://sitio.edu/cucuta/", "max_pages": 5000},
        headers=_auth(token),
    )
    assert res.status_code == 422


@patch("app.services.crawl_job_service.start_crawl_job", return_value="job-abc123")
def test_crawl_site_starts_job_and_returns_id(mock_start):
    token = _login_as()
    res = client.post(
        "/api/root/crawl-site",
        json={"seed_url": "https://sitio.edu/cucuta/", "max_depth": 1, "max_pages": 20},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.json()["job_id"] == "job-abc123"
    mock_start.assert_called_once_with("https://sitio.edu/cucuta/", None, 1, 20, None)


@patch(
    "app.services.crawl_job_service.get_job_status",
    return_value={
        "job_id": "job-abc123",
        "seed_url": "https://sitio.edu/cucuta/",
        "status": "running",
        "pages_indexed": 3,
        "pages_failed": 0,
        "current_url": "https://sitio.edu/cucuta/ingenieria",
        "skipped_binary_urls": [],
        "errors": [],
    },
)
def test_get_crawl_status_returns_progress(mock_status):
    token = _login_as()
    res = client.get("/api/root/crawl-site/job-abc123", headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["pages_indexed"] == 3


@patch("app.services.crawl_job_service.get_job_status", return_value=None)
def test_get_crawl_status_returns_404_for_unknown_job(mock_status):
    token = _login_as()
    res = client.get("/api/root/crawl-site/no-existe", headers=_auth(token))
    assert res.status_code == 404


@patch("app.services.crawl_job_service.cancel_job", return_value=True)
def test_cancel_crawl_job(mock_cancel):
    token = _login_as()
    res = client.post("/api/root/crawl-site/job-abc123/cancel", headers=_auth(token))
    assert res.status_code == 200
    mock_cancel.assert_called_once_with("job-abc123")


@patch("app.services.crawl_job_service.cancel_job", return_value=False)
def test_cancel_crawl_job_returns_404_when_not_found_or_finished(mock_cancel):
    token = _login_as()
    res = client.post("/api/root/crawl-site/no-existe/cancel", headers=_auth(token))
    assert res.status_code == 404
