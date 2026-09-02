"""Generación de embeddings locales con Sentence Transformers (gratuito, sin API externa)."""
from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Carga el modelo una sola vez (singleton) y lo reutiliza en toda la app.

    La primera vez que se ejecuta, descarga el modelo desde Hugging Face
    (~470MB para paraphrase-multilingual-MiniLM-L12-v2) y lo cachea en disco.
    """
    return SentenceTransformer(settings.EMBEDDING_MODEL)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Genera embeddings para una lista de textos (usado en ingestión, por lotes)."""
    model = get_embedding_model()
    vectors = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return vectors.tolist()


def embed_query(text: str) -> List[float]:
    """Genera el embedding de una sola consulta (pregunta del usuario)."""
    model = get_embedding_model()
    vector = model.encode([text], show_progress_bar=False, normalize_embeddings=True)
    return vector[0].tolist()
