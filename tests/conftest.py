"""Configuración compartida de pytest: variables de entorno de prueba y path del proyecto."""
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Se deben fijar ANTES de importar app.config, para no depender de un .env real
# ni contaminar la base vectorial usada por el proyecto en ejecución.
os.environ.setdefault("GROQ_API_KEY", "test-key-not-real")
os.environ.setdefault("VECTOR_DB_DIR", "vector_db_test")
os.environ.setdefault("HISTORY_DB_PATH", "history_test.db")
# TestClient reutiliza la misma "IP" simulada para todas las llamadas a
# /api/auth/login de toda la suite; con el límite de producción (10 por 5
# min) las pruebas empiezan a chocar entre sí con 429 mucho antes de que
# sea sospechoso de un ataque real.
os.environ.setdefault("LOGIN_RATE_LIMIT_MAX", "1000")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_vector_db():
    yield
    test_db_dir = ROOT_DIR / "vector_db_test"
    if test_db_dir.exists():
        shutil.rmtree(test_db_dir, ignore_errors=True)

    from app.services import history as history_service

    history_service.close()
    test_history_db = ROOT_DIR / "history_test.db"
    if test_history_db.exists():
        test_history_db.unlink()
