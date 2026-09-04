"""Recuperación semántica: embebe la pregunta, busca en el vector store y
filtra por umbral de similitud para evitar enviar contexto irrelevante al LLM."""
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings
from app.rag import vector_store
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

    Solo se devuelven los fragmentos cuya similitud supera SIMILARITY_THRESHOLD.
    Si ninguno lo supera, se devuelve una lista vacía: el chatbot debe entonces
    reconocer que no tiene información suficiente, en vez de alucinar.
    """
    top_k = top_k or settings.TOP_K
    query_embedding = embed_query(question)
    hits = vector_store.query(query_embedding, top_k=top_k)
    return [_to_chunk(h) for h in hits if h["similarity"] >= settings.SIMILARITY_THRESHOLD]


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
