"""Recuperación semántica: embebe la pregunta, busca en el vector store y
filtra por umbral de similitud para evitar enviar contexto irrelevante al LLM."""
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings
from app.rag import reranker, vector_store
from app.rag.embeddings import embed_query


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    document: str
    page: int
    similarity: float
    dependencia_id: Optional[int] = None


def _to_chunk(h: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=h["chunk_id"],
        text=h["text"],
        document=h["document"],
        page=h["page"],
        similarity=h["similarity"],
        dependencia_id=h.get("dependencia_id"),
    )


def retrieve(question: str, top_k: int = None) -> List[RetrievedChunk]:
    """Recupera los fragmentos más relevantes para una pregunta.

    Primero filtra por SIMILARITY_THRESHOLD (embeddings, barato) sobre un
    lote más amplio de candidatos (RERANK_CANDIDATE_K), y si RERANK_ENABLED
    los reordena/filtra por relevancia real con un cross-encoder local
    (ver app/rag/reranker.py) -- la similitud de embeddings por sí sola
    puede coincidir con fragmentos de un tema distinto que comparten
    vocabulario. Puede devolver una lista vacía (ni el umbral de embeddings
    ni el re-ranking encontraron algo realmente relevante): el chatbot debe
    entonces reconocer que no tiene información suficiente, en vez de
    alucinar.
    """
    top_k = top_k or settings.TOP_K
    query_embedding = embed_query(question)
    candidate_k = max(top_k, settings.RERANK_CANDIDATE_K)
    hits = vector_store.query(query_embedding, top_k=candidate_k)
    candidates = [_to_chunk(h) for h in hits if h["similarity"] >= settings.SIMILARITY_THRESHOLD]
    if not candidates:
        return []
    if not settings.RERANK_ENABLED:
        return candidates[:top_k]
    return reranker.rerank(question, candidates, top_k=top_k, min_score=settings.RERANK_MIN_SCORE)


def retrieve_below_threshold(question: str, top_k: int = None) -> List[RetrievedChunk]:
    """Como retrieve(), pero sin aplicar SIMILARITY_THRESHOLD -- se usa
    únicamente para alimentar sugerencias de reformulación cuando el
    chatbot ya determinó que no tiene información suficiente (ver
    chat_service.py y llm.suggest_clarifying_questions): ahí sí interesan
    los fragmentos con relación débil/parcial que retrieve() descarta a
    propósito para no contaminar el contexto real enviado al LLM."""
    top_k = top_k or settings.TOP_K
    query_embedding = embed_query(question)
    hits = vector_store.query(query_embedding, top_k=top_k)
    return [_to_chunk(h) for h in hits]


def build_context(chunks: List[RetrievedChunk]) -> str:
    """Construye el bloque de contexto que se enviará al LLM, citando la fuente
    de cada fragmento para que el modelo pueda referenciarla en su respuesta."""
    parts = []
    for c in chunks:
        parts.append(f"[Fuente: {c.document}, página {c.page}]\n{c.text}")
    return "\n\n---\n\n".join(parts)
