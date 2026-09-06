"""Pruebas del pipeline de chat_service.

Los saludos, agradecimientos y charla casual ya NO se detectan con
expresiones regulares propias: todo mensaje pasa por el LLM (con contexto de
documentos si se encontró alguno relevante, o vacío si no), y es el propio
modelo quien decide el tono de la respuesta según las instrucciones de
app/rag/llm.py. Estas pruebas verifican que el pipeline llama al LLM en
ambos casos y que "has_sufficient_info"/"sources" se derivan correctamente
del contenido de la respuesta generada (mockeada, sin llamar a Groq real).
"""
import uuid
from unittest.mock import MagicMock, patch

from app.config import settings
from app.rag import llm
from app.rag.retriever import RetrievedChunk
from app.services import chat_service


def _session_id() -> str:
    return f"chat-hostility-test-{uuid.uuid4().hex[:8]}"


def _fake_client_returning(json_content):
    fake_client = MagicMock()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json_content))]
    fake_client.chat.completions.create.return_value = completion
    return fake_client


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_llm_is_called_even_without_retrieved_chunks(mock_retrieve, mock_generate):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = (
        "¡Hola! Soy el asistente virtual de la Facultad de Ingeniería. "
        "¿En qué puedo ayudarte?"
    )

    response = chat_service.answer_question("s1", "hola")

    mock_generate.assert_called_once()
    assert response.has_sufficient_info is True
    assert response.sources == []


@patch("app.services.chat_service.retrieve_below_threshold")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_info_message_marks_insufficient_info(mock_retrieve, mock_generate, mock_retrieve_weak):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE
    mock_retrieve_weak.return_value = []

    response = chat_service.answer_question("s1", "¿cuál es el clima hoy?")

    assert response.has_sufficient_info is False
    assert response.sources == []
    assert response.suggestions == []


@patch("app.services.chat_service.llm.suggest_clarifying_questions")
@patch("app.services.chat_service.retrieve_below_threshold")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_info_response_includes_suggestions_when_weak_candidates_exist(
    mock_retrieve, mock_generate, mock_retrieve_weak, mock_suggest
):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE
    mock_retrieve_weak.return_value = [
        RetrievedChunk(chunk_id="c1", text="texto", document="doc.txt", page=1, similarity=0.3)
    ]
    mock_suggest.return_value = ["¿Tienen ingeniería en TIC?"]

    response = chat_service.answer_question("s1", "ing tic")

    assert response.suggestions == ["¿Tienen ingeniería en TIC?"]
    mock_suggest.assert_called_once()


@patch("app.services.chat_service.retrieve_below_threshold")
@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_no_suggestions_when_no_weak_candidates(mock_retrieve, mock_generate, mock_retrieve_weak):
    mock_retrieve.return_value = ([], 1.0)
    mock_generate.return_value = settings.NO_INFO_MESSAGE
    mock_retrieve_weak.return_value = []

    response = chat_service.answer_question("s1", "¿cuánto es 2+2?")

    assert response.suggestions == []


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_answer_with_chunks_includes_sources(mock_retrieve, mock_generate):
    chunk = RetrievedChunk(
        chunk_id="c1", text="Texto del reglamento...", document="Reglamento.pdf", page=5, similarity=0.8
    )
    mock_retrieve.return_value = ([chunk], 5.0)
    mock_generate.return_value = "Según el Reglamento Estudiantil, debes cumplir X."

    response = chat_service.answer_question("s1", "¿requisitos de grado?")

    assert response.has_sufficient_info is True
    assert len(response.sources) == 1
    assert response.sources[0].document == "Reglamento.pdf"


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_short_question_with_real_chunks_still_includes_sources(mock_retrieve, mock_generate):
    """Una pregunta de 2 palabras ("horario álgebra") puede ser una consulta
    real y específica -- si superó el umbral de similitud (por eso llegó
    con chunks no vacíos), debe citar su fuente igual que una pregunta
    larga. No hay que confundirla con un mensaje de relleno tipo "gracias"
    u "ok", que de todos modos no recupera chunks reales."""
    chunk = RetrievedChunk(
        chunk_id="c1", text="Horario de Álgebra Lineal: martes 9-11, salón A102.", document="Horario.xlsx", page=1, similarity=0.75
    )
    mock_retrieve.return_value = ([chunk], 5.0)
    mock_generate.return_value = "El horario de Álgebra Lineal es martes de 9 a 11, salón A102."

    response = chat_service.answer_question("s1", "horario álgebra")

    assert len(response.sources) == 1
    assert response.sources[0].document == "Horario.xlsx"


# --- llm.suggest_clarifying_questions (unidad, Groq simulado) -----------


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_returns_parsed_list(mock_get_client):
    mock_get_client.return_value = _fake_client_returning(
        '{"suggestions": ["¿Tienen ingeniería en TIC?", "¿Cuánto dura la carrera?"]}'
    )
    candidate = RetrievedChunk(chunk_id="c1", text="texto sobre TIC", document="faq.txt", page=1, similarity=0.3)

    result = llm.suggest_clarifying_questions("ing tic", [candidate])

    assert result == ["¿Tienen ingeniería en TIC?", "¿Cuánto dura la carrera?"]


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_handles_empty_list_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"suggestions": []}')
    candidate = RetrievedChunk(chunk_id="c1", text="texto no relacionado", document="doc.txt", page=1, similarity=0.26)

    assert llm.suggest_clarifying_questions("asdf", [candidate]) == []


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_handles_malformed_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("esto no es json")
    candidate = RetrievedChunk(chunk_id="c1", text="texto", document="doc.txt", page=1, similarity=0.3)

    assert llm.suggest_clarifying_questions("pregunta", [candidate]) == []


@patch("app.rag.llm.get_client")
def test_suggest_clarifying_questions_handles_client_exception(mock_get_client):
    mock_get_client.side_effect = RuntimeError("groq caído")
    candidate = RetrievedChunk(chunk_id="c1", text="texto", document="doc.txt", page=1, similarity=0.3)

    assert llm.suggest_clarifying_questions("pregunta", [candidate]) == []


def test_suggest_clarifying_questions_returns_empty_without_candidates():
    assert llm.suggest_clarifying_questions("pregunta", []) == []


# --- Detector de hostilidad (app/services/hostility_service.py) ---


@patch("app.rag.llm.generate_answer")
@patch("app.services.chat_service.retrieve_context")
def test_hostile_message_skips_retrieval_and_generation(mock_retrieve, mock_generate, monkeypatch):
    """Un mensaje hostil nunca debe gastar retrieval ni una llamada al LLM
    -- se corta antes, igual que ya hace el corte de needs_human()."""
    monkeypatch.setattr(settings, "HOSTILITY_STRIKE_LIMIT", 3)
    response = chat_service.answer_question(_session_id(), "eres un idiota")

    mock_retrieve.assert_not_called()
    mock_generate.assert_not_called()
    assert "1/3" in response.answer


def test_hostility_block_triggers_after_strike_limit(monkeypatch):
    monkeypatch.setattr(settings, "HOSTILITY_STRIKE_LIMIT", 2)
    monkeypatch.setattr(settings, "HOSTILITY_BLOCK_HOURS", 1.0)
    session_id = _session_id()

    with patch("app.services.chat_service.retrieve_context"), patch("app.rag.llm.generate_answer"):
        first = chat_service.answer_question(session_id, "eres un idiota")
        second = chat_service.answer_question(session_id, "eres un idiota")
        third = chat_service.answer_question(session_id, "una pregunta normal cualquiera")

    assert "1/2" in first.answer
    assert "bloqueado" in second.answer.lower()
    assert "sigue bloqueado" in third.answer.lower()


# --- Extracción de texto de imágenes (app/rag/llm.py::extract_text_from_image) ---


@patch("app.rag.llm.get_client")
def test_extract_text_from_image_sends_base64_image_and_returns_text(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("Título: Clase con el Congreso\nFecha: 11 de septiembre")

    result = llm.extract_text_from_image(b"contenido binario falso de una imagen", ".png")

    assert "Congreso" in result
    sent_kwargs = mock_get_client.return_value.chat.completions.create.call_args.kwargs
    content_blocks = sent_kwargs["messages"][0]["content"]
    image_block = next(b for b in content_blocks if b["type"] == "image_url")
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")


@patch("app.rag.llm.get_client")
def test_extract_text_from_image_strips_thinking_block(mock_get_client):
    """El modelo de visión (Qwen, razonamiento) puede meter su
    "pensamiento" inline como <think>...</think> antes de la respuesta --
    confirmado con una imagen real -- y no debe llegarle al administrador."""
    mock_get_client.return_value = _fake_client_returning(
        "<think>\nAnalizando la imagen paso a paso...\n</think>\n\nTítulo: Clase con el Congreso"
    )

    result = llm.extract_text_from_image(b"contenido binario falso", ".jpg")

    assert result == "Título: Clase con el Congreso"
    assert "<think>" not in result
    assert "Analizando" not in result


def test_estimate_tokens_still_handles_plain_string_content():
    messages = [{"role": "user", "content": "a" * 400}]

    assert llm._estimate_tokens(messages, max_completion_tokens=100) == 400 // 4 + 100


# --- Nombre de archivo sugerido (app/rag/llm.py::suggest_filename_from_text) ---


@patch("app.rag.llm.get_client")
def test_suggest_filename_from_text_returns_parsed_name(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"filename": "clase-congreso-de-la-republica"}')

    result = llm.suggest_filename_from_text("Una clase con el Congreso de la República...")

    assert result == "clase-congreso-de-la-republica"


@patch("app.rag.llm.get_client")
def test_suggest_filename_from_text_returns_none_on_unparseable_response(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("esto no es json")

    assert llm.suggest_filename_from_text("texto cualquiera") is None


@patch("app.rag.llm.get_client")
def test_suggest_filename_from_text_returns_none_on_client_exception(mock_get_client):
    mock_get_client.side_effect = RuntimeError("groq caído")

    assert llm.suggest_filename_from_text("texto cualquiera") is None


# --- Limitador de tasa propio para el modelo de visión (app/rag/llm.py) ---


@patch("app.rag.llm.get_client")
def test_vision_model_call_uses_vision_rate_limiter(mock_get_client):
    mock_get_client.return_value = _fake_client_returning("texto extraído")

    with (
        patch.object(llm._vision_rate_limiter, "acquire") as mock_vision_acquire,
        patch.object(llm._rate_limiter, "acquire") as mock_main_acquire,
    ):
        llm.extract_text_from_image(b"contenido falso de imagen", ".jpg")

    # La cuota de visión es de tokens de SALIDA por minuto -- la imagen de
    # entrada no debe sumarse, o una sola llamada ya superaría todo el cupo
    # (ver rate_limiter.py::GroqRateLimiter.acquire) y nunca podría pasar.
    mock_vision_acquire.assert_called_once_with(settings.GROQ_VISION_MAX_COMPLETION_TOKENS)
    mock_main_acquire.assert_not_called()


@patch("app.rag.llm.get_client")
def test_text_model_call_uses_main_rate_limiter(mock_get_client):
    mock_get_client.return_value = _fake_client_returning('{"filename": "nombre"}')

    with (
        patch.object(llm._vision_rate_limiter, "acquire") as mock_vision_acquire,
        patch.object(llm._rate_limiter, "acquire") as mock_main_acquire,
    ):
        llm.suggest_filename_from_text("texto cualquiera")

    mock_main_acquire.assert_called_once()
    mock_vision_acquire.assert_not_called()
