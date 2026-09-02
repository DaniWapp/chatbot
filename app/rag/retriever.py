"""Recuperación semántica: embebe la pregunta, busca en el vector store y
filtra por umbral de similitud para evitar enviar contexto irrelevante al LLM."""
from dataclasses import dataclass
from typing import List

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


def retrieve(question: str, top_k: int = None) -> List[RetrievedChunk]:
    """Recupera los fragmentos más relevantes para una pregunta.

    Solo se devuelven los fragmentos cuya similitud supera SIMILARITY_THRESHOLD.
    Si ninguno lo supera, se devuelve una lista vacía: el chatbot debe entonces
    reconocer que no tiene información suficiente, en vez de alucinar.
    """
    top_k = top_k or settings.TOP_K
    query_embedding = embed_query(question)
    hits = vector_store.query(query_embedding, top_k=top_k)

    relevant = [
        RetrievedChunk(
            chunk_id=h["chunk_id"],
            text=h["text"],
            document=h["document"],
            page=h["page"],
            similarity=h["similarity"],
        )
        for h in hits
        if h["similarity"] >= settings.SIMILARITY_THRESHOLD
    ]
    return relevant


def build_context(chunks: List[RetrievedChunk]) -> str:
    """Construye el bloque de contexto que se enviará al LLM, citando la fuente
    de cada fragmento para que el modelo pueda referenciarla en su respuesta."""
    parts = []
    for c in chunks:
        parts.append(f"[Fuente: {c.document}, página {c.page}]\n{c.text}")
    return "\n\n---\n\n".join(parts)
