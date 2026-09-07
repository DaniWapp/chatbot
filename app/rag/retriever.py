"""Recuperación semántica: embebe la pregunta, busca en el vector store y
filtra por umbral de similitud para evitar enviar contexto irrelevante al LLM."""
import re
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings
from app.rag import reranker, vector_store
from app.rag.embeddings import embed_query
from app.services import ingest_service

_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")


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


def drop_superseded_by_vigencia(question: str, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """Si el resultado incluye chunks de 2+ documentos con vigente_desde
    asignado, se descartan los de vigencia más antigua -- el documento más
    reciente los reemplaza (ej. Calendario 2027 sobre Calendario 2026).
    Excepción: si la pregunta menciona explícitamente un año que coincide
    con la vigencia de alguno de esos documentos, se respeta ese pedido
    puntual en vez de imponer el más reciente (ej. "¿cuál es el calendario
    de 2026?" con ambos calendarios compitiendo debe responder con el de
    2026). Documentos sin vigente_desde (None) nunca se descartan por esta
    regla -- son generales, sin caducidad."""
    vigencias = {c.document: ingest_service.get_document_vigencia(c.document) for c in chunks}
    con_vigencia = {doc: v for doc, v in vigencias.items() if v}
    if len(con_vigencia) < 2:
        return chunks

    years_in_question = set(_YEAR_PATTERN.findall(question))
    if years_in_question:
        matching_docs = {doc for doc, v in con_vigencia.items() if v[:4] in years_in_question}
        if matching_docs:
            return [c for c in chunks if c.document not in con_vigencia or c.document in matching_docs]

    mas_reciente = max(con_vigencia.values())
    superados = {doc for doc, v in con_vigencia.items() if v < mas_reciente}
    return [c for c in chunks if c.document not in superados]


def retrieve(question: str, top_k: int = None) -> List[RetrievedChunk]:
    """Recupera los fragmentos más relevantes para una pregunta.

    Trae un lote amplio de candidatos por embeddings (RERANK_CANDIDATE_K)
    y, si RERANK_ENABLED, se los pasa TODOS al cross-encoder local (ver
    app/rag/reranker.py) sin pre-filtrar por SIMILARITY_THRESHOLD -- caso
    real verificado: para "la clase de calculo diferencial", el embedding
    de la fila "Cálculo Diferencial" queda por debajo de ese umbral
    (0.27 vs. 0.35) y hasta detrás de una fila de "Álgebra Lineal" no
    relacionada (el modelo de embeddings confunde estas dos frases cortas
    de matemáticas), pero el cross-encoder sí la distingue perfectamente
    en cuanto se le muestra -- el problema nunca fue de juicio de
    relevancia, era que el fragmento correcto no llegaba a esa etapa.
    Con re-ranking activo, RERANK_MIN_SCORE es entonces el único filtro
    de relevancia real. Sin re-ranking (RERANK_ENABLED=False), no hay un
    juez más preciso disponible, así que ahí sí se usa SIMILARITY_THRESHOLD
    como antes. Puede devolver una lista vacía: el chatbot debe entonces
    reconocer que no tiene información suficiente, en vez de alucinar.
    """
    top_k = top_k or settings.TOP_K
    query_embedding = embed_query(question)
    candidate_k = max(top_k, settings.RERANK_CANDIDATE_K)
    hits = vector_store.query(query_embedding, top_k=candidate_k)

    if settings.RERANK_ENABLED:
        candidates = [_to_chunk(h) for h in hits]
        if not candidates:
            return []
        result = reranker.rerank(question, candidates, top_k=top_k, min_score=settings.RERANK_MIN_SCORE)
    else:
        candidates = [_to_chunk(h) for h in hits if h["similarity"] >= settings.SIMILARITY_THRESHOLD]
        if not candidates:
            return []
        result = candidates[:top_k]
    return drop_superseded_by_vigencia(question, result)


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
