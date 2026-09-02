"""Pruebas del umbral de relevancia en la recuperación semántica.

Se simulan (mock) el embedding de la consulta y la respuesta del vector store
para no depender de descargar el modelo de embeddings real en cada test.
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


@patch("app.rag.retriever.vector_store.query", return_value=FAKE_HITS)
@patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3])
def test_relevant_question_keeps_only_chunks_above_threshold(mock_embed, mock_query):
    results = retriever.retrieve("¿Cuáles son los requisitos de grado?")

    assert len(results) == 1
    assert results[0].document == "Reglamento.pdf"
    assert results[0].similarity >= 0.35


@patch("app.rag.retriever.vector_store.query", return_value=[FAKE_HITS[1]])
@patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3])
def test_irrelevant_question_returns_no_chunks(mock_embed, mock_query):
    results = retriever.retrieve("¿Dónde está la cafetería?")

    assert results == []


@patch("app.rag.retriever.vector_store.query", return_value=[])
@patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3])
def test_empty_index_returns_no_chunks(mock_embed, mock_query):
    results = retriever.retrieve("cualquier pregunta")

    assert results == []


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
