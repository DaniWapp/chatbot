"""Re-ranking local de fragmentos recuperados (sentence-transformers
CrossEncoder, gratuito, sin llamadas a Groq).

La similitud de embeddings (usada en retriever.py) mide parecido general
de significado, no si un fragmento realmente responde la pregunta -- un
seguimiento corto como "duración" puede coincidir por embeddings con
fragmentos de un tema totalmente distinto (ej. horas de una práctica) que
casualmente comparten vocabulario. El cross-encoder compara la pregunta y
el fragmento juntos (no por separado, como los embeddings) y da un juicio
de relevancia mucho más preciso -- a costa de ser más lento, por eso solo
se aplica sobre los pocos candidatos ya filtrados por embeddings, nunca
sobre todo el índice."""
import math
from functools import lru_cache
from typing import TYPE_CHECKING, List

from sentence_transformers import CrossEncoder

from app.config import settings

if TYPE_CHECKING:
    # Import solo para chequeo de tipos: retriever.py importa este módulo,
    # así que un import normal aquí crearía un ciclo en tiempo de ejecución.
    from app.rag.retriever import RetrievedChunk


@lru_cache(maxsize=1)
def get_reranker_model() -> CrossEncoder:
    """Carga el modelo una sola vez (singleton), mismo patrón que
    embeddings.py::get_embedding_model."""
    return CrossEncoder(settings.RERANKER_MODEL)


def rerank(question: str, chunks: "List[RetrievedChunk]", top_k: int, min_score: float) -> "List[RetrievedChunk]":
    """Reordena chunks por relevancia real a la pregunta y descarta los
    que queden debajo de min_score -- puede devolver una lista vacía si
    nada es realmente relevante, aunque la búsqueda por embeddings sí haya
    encontrado algo por encima de SIMILARITY_THRESHOLD.

    CrossEncoder.predict() devuelve logits crudos (no acotados a 0-1) --
    aplicamos sigmoide para obtener una confianza interpretable en ese
    rango antes de compararla con min_score. Sin esto, un min_score
    pensado como probabilidad (ej. 0.3) rechaza incluso fragmentos
    correctos, que en este modelo suelen dar logits negativos."""
    if not chunks:
        return []
    model = get_reranker_model()
    raw_scores = model.predict([(question, c.text) for c in chunks])
    scores = [1 / (1 + math.exp(-s)) for s in raw_scores]
    scored = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
    return [chunk for chunk, score in scored[:top_k] if score >= min_score]
