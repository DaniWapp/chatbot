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
# Mismo motivo: el limitador de tasa de Groq es un único objeto compartido
# por todo el proceso (ver app/rag/rate_limiter.py). Groq mismo ya está
# mockeado en las pruebas, pero el limitador no sabe eso -- sin este ajuste,
# suficientes pruebas que pasen por app.rag.llm dentro de la misma ventana
# de 60s del proceso de pytest empezarían a dormir de verdad.
os.environ.setdefault("GROQ_MAX_REQUESTS_PER_MINUTE", "100000")
os.environ.setdefault("GROQ_MAX_TOKENS_PER_MINUTE", "100000000")

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
