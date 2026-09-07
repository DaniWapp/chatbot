"""Pruebas del umbral de relevancia en la recuperación semántica.

Se simulan (mock) el embedding de la consulta, la respuesta del vector store,
y el re-ranking para no depender de descargar el modelo de embeddings ni el
cross-encoder real en cada test.
"""
from unittest.mock import patch

from app.rag import retriever

FAKE_HITS = [
    {
        "chunk_id": "a1",
        "text": "Los requisitos de grado incluyen aprobar el 100% de los créditos.",
        "document": "Reglamento.pdf",
        "page": 20,
        "similarity": 0.82,
    },
    {
        "chunk_id": "a2",
        "text": "La cafetería central abre de lunes a viernes.",
        "document": "Otro.pdf",
        "page": 3,
        "similarity": 0.12,
    },
]


def _rerank_keep_only_a1(question, chunks, top_k, min_score):
    """Simula un re-ranker real que sí filtra por relevancia -- el chunk
    irrelevante nunca sobrevive, sin importar qué tan alta haya sido su
    similitud de embeddings."""
    return [c for c in chunks if c.chunk_id == "a1"][:top_k]


@patch("app.rag.retriever.reranker.rerank", side_effect=_rerank_keep_only_a1)
@patch("app.rag.retriever.vector_store.lexical_query", return_value=[])
@patch("app.rag.retriever.vector_store.query", return_value=FAKE_HITS)
@patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3])
def test_rerank_receives_all_candidates_without_prefiltering_by_embedding_threshold(
    mock_embed, mock_query, mock_lexical, mock_rerank
):
    """Caso real que motivó este cambio: "Materia: Cálculo Diferencial"
    tenía una similitud de embeddings (0.27) por debajo de
    SIMILARITY_THRESHOLD (0.35) -- y hasta menor que una fila de "Álgebra
    Lineal" no relacionada -- porque el modelo de embeddings confunde
    estas dos frases cortas de matemáticas. El cross-encoder sí las
    distingue perfectamente en cuanto se le muestran ambas. Por eso
    retrieve() ya NO descarta candidatos por SIMILARITY_THRESHOLD antes
    de re-rankear (con RERANK_ENABLED, el caso normal): le pasa TODOS los
    candidatos al re-ranker -- aquí, incluso el de similitud 0.12, muy
    por debajo de 0.35 -- y es el re-ranker (mockeado aquí, cross-encoder
    real en producción) quien decide qué es realmente relevante."""
    results = retriever.retrieve("¿Cuáles son los requisitos de grado?")

    received_chunks = mock_rerank.call_args[0][1]
    assert {c.chunk_id for c in received_chunks} == {"a1", "a2"}

    assert len(results) == 1
    assert results[0].document == "Reglamento.pdf"


@patch("app.rag.retriever.reranker.rerank", return_value=[])
@patch("app.rag.retriever.vector_store.query", return_value=[FAKE_HITS[1]])
@patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3])
def test_irrelevant_question_returns_no_chunks(mock_embed, mock_query, mock_rerank):
    """El re-ranker (mockeado -- ver test de arriba para por qué ya no se
    puede confiar en SIMILARITY_THRESHOLD solo) es quien decide que nada
    es relevante; retrieve() debe respetar una lista vacía."""
    results = retriever.retrieve("¿Dónde está la cafetería?")

    assert results == []


@patch("app.rag.retriever.vector_store.query", return_value=[])
@patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3])
def test_empty_index_returns_no_chunks(mock_embed, mock_query):
    results = retriever.retrieve("cualquier pregunta")

    assert results == []


# --- Vigencia por documento: el más reciente reemplaza al anterior ---


def _chunk(chunk_id, document, text="texto"):
    return retriever.RetrievedChunk(chunk_id=chunk_id, text=text, document=document, page=1, similarity=0.9)


def _vigencia_map(mapping):
    return lambda document: mapping.get(document)


@patch("app.rag.retriever.ingest_service.get_document_vigencia")
def test_drop_superseded_keeps_only_most_recent_when_question_has_no_year(mock_vigencia):
    mock_vigencia.side_effect = _vigencia_map(
        {"Calendario2026.txt": "2026-01-01", "Calendario2027.txt": "2027-01-01"}
    )
    chunks = [_chunk("a", "Calendario2026.txt"), _chunk("b", "Calendario2027.txt")]

    result = retriever.drop_superseded_by_vigencia("¿Cuándo empiezan las matrículas?", chunks)

    assert [c.document for c in result] == ["Calendario2027.txt"]


@patch("app.rag.retriever.ingest_service.get_document_vigencia")
def test_drop_superseded_respects_explicit_year_in_question(mock_vigencia):
    """Si la pregunta pide explícitamente el año del documento más viejo,
    ese gana -- no se le impone el más reciente (ver caso límite en el
    plan: "¿cuál es el calendario de 2026?" con el 2027 ya subido).
    vigente_desde representa el período que cada documento cubre (por eso
    el admin le pone la fecha desde la que ese calendario aplica, no
    necesariamente la fecha real en que lo subió)."""
    mock_vigencia.side_effect = _vigencia_map(
        {"Calendario2026.txt": "2026-01-01", "Calendario2027.txt": "2027-01-01"}
    )
    chunks = [_chunk("a", "Calendario2026.txt"), _chunk("b", "Calendario2027.txt")]

    result = retriever.drop_superseded_by_vigencia("¿Cuál es el calendario de 2026?", chunks)

    assert [c.document for c in result] == ["Calendario2026.txt"]


@patch("app.rag.retriever.ingest_service.get_document_vigencia")
def test_drop_superseded_never_drops_document_without_vigencia(mock_vigencia):
    mock_vigencia.side_effect = _vigencia_map(
        {"Calendario2026.txt": "2026-01-01", "Calendario2027.txt": "2027-01-01", "Reglamento.pdf": None}
    )
    chunks = [_chunk("a", "Calendario2026.txt"), _chunk("b", "Calendario2027.txt"), _chunk("c", "Reglamento.pdf")]

    result = retriever.drop_superseded_by_vigencia("pregunta cualquiera", chunks)

    assert [c.document for c in result] == ["Calendario2027.txt", "Reglamento.pdf"]


@patch("app.rag.retriever.ingest_service.get_document_vigencia")
def test_drop_superseded_does_nothing_with_fewer_than_two_dated_documents(mock_vigencia):
    mock_vigencia.side_effect = _vigencia_map({"Calendario2027.txt": "2027-01-01", "Reglamento.pdf": None})
    chunks = [_chunk("a", "Calendario2027.txt"), _chunk("b", "Reglamento.pdf")]

    result = retriever.drop_superseded_by_vigencia("pregunta cualquiera", chunks)

    assert result == chunks


def test_build_context_includes_source_labels():
    chunks = [
        retriever.RetrievedChunk(
            chunk_id="a1", text="Texto de prueba.", document="Reglamento.pdf", page=20, similarity=0.9
        )
    ]

    context = retriever.build_context(chunks)

    assert "Reglamento.pdf" in context
    assert "página 20" in context
    assert "Texto de prueba." in context
