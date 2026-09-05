"""Pruebas de la caché de respuestas por huella de contexto recuperado
(app/services/answer_cache_service.py). Cada prueba usa contenido único
(uuid) para no chocar con entradas guardadas por otras pruebas en la
misma base de datos de prueba compartida durante la sesión de pytest."""
import uuid
from unittest.mock import patch

from app.config import settings
from app.rag.retriever import RetrievedChunk
from app.services import answer_cache_service, chat_service


def _chunk(chunk_id: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, text=text, document="doc.txt", page=1, similarity=0.9)


# --- Unidad: compute_context_hash / is_cache_eligible --------------------


def test_compute_context_hash_ignores_chunk_order():
    a = _chunk("a", "texto A")
    b = _chunk("b", "texto B")
    assert answer_cache_service.compute_context_hash([a, b]) == answer_cache_service.compute_context_hash([b, a])


def test_compute_context_hash_changes_when_source_text_changes():
    original = _chunk("a", "texto original")
    edited = _chunk("a", "texto editado")  # mismo chunk_id, texto distinto (documento editado)
    assert answer_cache_service.compute_context_hash([original]) != answer_cache_service.compute_context_hash([edited])


def test_is_cache_eligible_requires_chunks_and_minimum_length():
    chunk = _chunk("a", "texto")
    assert answer_cache_service.is_cache_eligible("pregunta larga de verdad", [chunk]) is True
    assert answer_cache_service.is_cache_eligible("sí", [chunk]) is False
    assert answer_cache_service.is_cache_eligible("pregunta larga de verdad", []) is False


# --- Integración: chat_service.answer_question ----------------------------


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_second_paraphrase_reuses_cached_answer_without_calling_llm(mock_retrieve, mock_generate):
    unique = uuid.uuid4().hex
    chunk = _chunk(f"cache-{unique}", f"Contenido único {unique} sobre ingeniería de sistemas")
    mock_retrieve.return_value = ([chunk], 1.0)
    mock_generate.return_value = f"Respuesta sobre ingeniería de sistemas {unique}."

    first = chat_service.answer_question("s-cache-1", "ingeniería de sistemas")
    second = chat_service.answer_question("s-cache-2", "ingeniería en sistemas")

    mock_generate.assert_called_once()  # la segunda pregunta no volvió a llamar al LLM
    assert second.answer == first.answer == mock_generate.return_value


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_editing_source_content_invalidates_cache(mock_retrieve, mock_generate):
    unique = uuid.uuid4().hex
    chunk_id = f"cache-edit-{unique}"
    mock_retrieve.return_value = ([_chunk(chunk_id, f"Costos originales {unique}")], 1.0)
    mock_generate.return_value = f"Los costos son X ({unique})."

    chat_service.answer_question("s-edit-1", "cuáles son los costos de la carrera")
    assert mock_generate.call_count == 1

    # El documento de origen "cambia" -- mismo chunk_id, texto distinto.
    mock_retrieve.return_value = ([_chunk(chunk_id, f"Costos actualizados {unique}")], 1.0)
    mock_generate.return_value = f"Los costos ahora son Y ({unique})."

    result = chat_service.answer_question("s-edit-2", "cuáles son los costos de la carrera")

    assert mock_generate.call_count == 2  # la caché quedó invalidada por el cambio de contenido
    assert result.answer == mock_generate.return_value


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_short_message_is_never_cached(mock_retrieve, mock_generate):
    unique = uuid.uuid4().hex
    mock_retrieve.return_value = ([_chunk(f"short-{unique}", f"Texto {unique}")], 1.0)
    mock_generate.return_value = f"Respuesta {unique}"

    chat_service.answer_question("s-short-1", "gracias")
    chat_service.answer_question("s-short-2", "gracias")

    assert mock_generate.call_count == 2  # un mensaje de 1 palabra nunca es elegible para caché


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_info_answer_is_never_cached(mock_retrieve, mock_generate):
    unique = uuid.uuid4().hex
    mock_retrieve.return_value = ([_chunk(f"noinfo-{unique}", f"Texto no relacionado {unique}")], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE

    chat_service.answer_question("s-noinfo-1", "una pregunta bastante larga y especifica")
    chat_service.answer_question("s-noinfo-2", "una pregunta bastante larga y especifica")

    assert mock_generate.call_count == 2  # nunca vale la pena reutilizar "no encontré información"


# --- Integración: chat_service.stream_answer ------------------------------


@patch("app.rag.llm.stream_answer")
@patch("app.services.chat_service.retrieve_context")
def test_stream_answer_reuses_cache_without_calling_llm_stream(mock_retrieve, mock_llm_stream):
    unique = uuid.uuid4().hex
    mock_retrieve.return_value = ([_chunk(f"stream-{unique}", f"Contenido único de streaming {unique}")], 1.0)
    mock_llm_stream.return_value = iter(["Respuesta ", f"en vivo {unique}."])

    list(chat_service.stream_answer("s-stream-1", "pregunta sobre streaming"))
    mock_llm_stream.assert_called_once()

    events_second = list(chat_service.stream_answer("s-stream-2", "consulta sobre streaming"))

    mock_llm_stream.assert_called_once()  # no se volvió a llamar -- se sirvió desde caché
    deltas = [e["text"] for e in events_second if e["type"] == "delta"]
    assert "".join(deltas) == f"Respuesta en vivo {unique}."
