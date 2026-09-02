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

    # --- Historial ---
    MAX_HISTORY_TURNS: int = _get_int("MAX_HISTORY_TURNS", 3)

    # --- Backend ---
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0")
    BACKEND_PORT: int = _get_int("BACKEND_PORT", 8000)

    # --- Documentos ---
    DOCUMENTS_DIR: Path = BASE_DIR / os.getenv("DOCUMENTS_DIR", "documents")
    VECTOR_DB_DIR: Path = BASE_DIR / os.getenv("VECTOR_DB_DIR", "vector_db")
    MAX_FILE_SIZE_MB: int = _get_int("MAX_FILE_SIZE_MB", 25)

    ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}
    COLLECTION_NAME = "facultad_ingenieria"

    NO_INFO_MESSAGE = (
        "No encontré información suficiente en la documentación disponible "
        "para responder esta pregunta."
    )


settings = Settings()
