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

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_vector_db():
    yield
    test_db_dir = ROOT_DIR / "vector_db_test"
    if test_db_dir.exists():
        shutil.rmtree(test_db_dir, ignore_errors=True)
