"""Configuración centralizada del chatbot, cargada desde variables de entorno (.env)."""
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _get_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


class Settings:
    BASE_DIR: Path = BASE_DIR

    # --- Groq ---
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    # --- Embeddings ---
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

    # --- RAG ---
    TOP_K: int = _get_int("TOP_K", 4)
    CHUNK_SIZE: int = _get_int("CHUNK_SIZE", 1000)
    CHUNK_OVERLAP: int = _get_int("CHUNK_OVERLAP", 150)
    SIMILARITY_THRESHOLD: float = _get_float("SIMILARITY_THRESHOLD", 0.35)
    # Umbral más bajo, solo para decidir si vale la pena pedirle al LLM
    # sugerencias de reformulación cuando no hay información suficiente (ver
    # chat_service.py) -- evita llamar al LLM cuando ni siquiera hay una
    # señal débil de relación con la pregunta.
    SUGGESTION_MIN_SIMILARITY: float = _get_float("SUGGESTION_MIN_SIMILARITY", 0.25)

    # --- Historial ---
    MAX_HISTORY_TURNS: int = _get_int("MAX_HISTORY_TURNS", 3)
    HISTORY_DB_PATH: Path = BASE_DIR / os.getenv("HISTORY_DB_PATH", "history.db")
    # Respaldo periódico de history.db (todas las conversaciones): un solo
    # archivo SQLite sin respaldo se pierde entero si se corrompe o se borra
    # por error.
    HISTORY_BACKUP_DIR: Path = BASE_DIR / os.getenv("HISTORY_BACKUP_DIR", "backups")
    HISTORY_BACKUP_INTERVAL_SECONDS: int = _get_int("HISTORY_BACKUP_INTERVAL_SECONDS", 6 * 60 * 60)
    HISTORY_BACKUP_RETENTION: int = _get_int("HISTORY_BACKUP_RETENTION", 14)

    # Si una dependencia no responde (ni un solo mensaje de asesor) en este
    # tiempo desde que se le asignó una conversación, se redirige
    # automáticamente al administrador general.
    AUTO_ESCALATION_TIMEOUT_SECONDS: int = _get_int("AUTO_ESCALATION_TIMEOUT_SECONDS", 5 * 60)
    AUTO_ESCALATION_CHECK_INTERVAL_SECONDS: int = _get_int("AUTO_ESCALATION_CHECK_INTERVAL_SECONDS", 60)

    # --- Backend ---
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0")
    BACKEND_PORT: int = _get_int("BACKEND_PORT", 8000)

    # --- Seguridad ---
    # Orígenes permitidos por CORS, separados por coma. Por defecto solo el
    # propio backend (localhost) y la IP de red local típica de este proyecto.
    ALLOWED_ORIGINS: list = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",") if o.strip()
    ]
    # Límite de peticiones a /api/chat y /api/chat/stream por IP, para evitar
    # que alguien agote la cuota de Groq con peticiones repetidas.
    CHAT_RATE_LIMIT_MAX: int = _get_int("CHAT_RATE_LIMIT_MAX", 15)
    CHAT_RATE_LIMIT_WINDOW_SECONDS: int = _get_int("CHAT_RATE_LIMIT_WINDOW_SECONDS", 60)
    # Límite de intentos de /api/auth/login por IP (fuerza bruta), ahora que
    # las cuentas de administrador tienen contraseñas reales.
    LOGIN_RATE_LIMIT_MAX: int = _get_int("LOGIN_RATE_LIMIT_MAX", 10)
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = _get_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300)

    # --- Documentos ---
    DOCUMENTS_DIR: Path = BASE_DIR / os.getenv("DOCUMENTS_DIR", "documents")
    VECTOR_DB_DIR: Path = BASE_DIR / os.getenv("VECTOR_DB_DIR", "vector_db")
    MAX_FILE_SIZE_MB: int = _get_int("MAX_FILE_SIZE_MB", 25)

    ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".xlsx"}
    COLLECTION_NAME = "facultad_ingenieria"

    # --- Institución (logo) ---
    LOGO_DIR: Path = BASE_DIR / "frontend" / "branding"
    ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
    MAX_LOGO_SIZE_MB: int = _get_int("MAX_LOGO_SIZE_MB", 5)

    NO_INFO_MESSAGE = (
        "No encontré información suficiente en la documentación disponible "
        "para responder esta pregunta."
    )


settings = Settings()
