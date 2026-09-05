"""Pruebas del re-ranking local (app/rag/reranker.py). Se mockea el modelo
CrossEncoder para no descargarlo/ejecutarlo en cada test."""
from unittest.mock import MagicMock, patch

from app.rag import reranker
from app.rag.retriever import RetrievedChunk


def _chunk(chunk_id: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, text=text, document="doc.txt", page=1, similarity=0.9)


def _fake_model(scores):
    model = MagicMock()
    model.predict.return_value = scores
    return model


@patch("app.rag.reranker.get_reranker_model")
def test_rerank_reorders_by_score_descending(mock_get_model):
    a, b, c = _chunk("a", "texto A"), _chunk("b", "texto B"), _chunk("c", "texto C")
    mock_get_model.return_value = _fake_model([0.2, 0.9, 0.5])  # b > c > a

    result = reranker.rerank("pregunta", [a, b, c], top_k=3, min_score=0.0)

    assert [chunk.chunk_id for chunk in result] == ["b", "c", "a"]


@patch("app.rag.reranker.get_reranker_model")
def test_rerank_drops_chunks_below_min_score(mock_get_model):
    a, b = _chunk("a", "texto relevante"), _chunk("b", "texto irrelevante")
    mock_get_model.return_value = _fake_model([0.8, 0.1])

    result = reranker.rerank("pregunta", [a, b], top_k=3, min_score=0.3)

    assert [chunk.chunk_id for chunk in result] == ["a"]


@patch("app.rag.reranker.get_reranker_model")
def test_rerank_can_drop_everything(mock_get_model):
    a, b = _chunk("a", "texto"), _chunk("b", "otro texto")
    mock_get_model.return_value = _fake_model([0.1, 0.05])

    result = reranker.rerank("pregunta", [a, b], top_k=3, min_score=0.3)

    assert result == []


@patch("app.rag.reranker.get_reranker_model")
def test_rerank_respects_top_k(mock_get_model):
    chunks = [_chunk(str(i), f"texto {i}") for i in range(5)]
    mock_get_model.return_value = _fake_model([0.9, 0.8, 0.7, 0.6, 0.5])

    result = reranker.rerank("pregunta", chunks, top_k=2, min_score=0.0)

    assert len(result) == 2
    assert [chunk.chunk_id for chunk in result] == ["0", "1"]


def test_rerank_empty_chunks_never_calls_model():
    with patch("app.rag.reranker.get_reranker_model") as mock_get_model:
        result = reranker.rerank("pregunta", [], top_k=3, min_score=0.3)

    assert result == []
    mock_get_model.assert_not_called()
