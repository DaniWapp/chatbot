"""Caché de respuestas por huella del contexto recuperado (no por
pregunta) -- ver app/services/history.py (tabla answer_cache) para el
razonamiento completo.

El prompt de sistema (app/rag/llm.py::_build_system_prompt) obliga al LLM
a responder únicamente con el CONTEXTO recuperado, así que lo que
determina la respuesta es qué fragmentos se recuperaron, no la redacción
exacta de la pregunta. Dos preguntas distintas que recuperan los mismos
fragmentos comparten context_hash y reutilizan la misma respuesta; si el
texto de origen cambia (se edita un documento y se reingesta), el hash
cambia y la entrada vieja simplemente deja de coincidir -- invalidación
automática, sin clasificar manualmente qué información es "cambiante"."""
import hashlib
from typing import List, Optional

from app.config import settings
from app.rag.retriever import RetrievedChunk
from app.services import history as history_service

# Mismo umbral que chat_service.py::_looks_too_short_for_citation (no se
# importa de ahí para evitar un ciclo: chat_service importa este módulo).
# Un mensaje de 1-2 palabras ("sí", "gracias", "¿y los costos?") suele
# depender de lo que se dijo antes en la conversación -- no es seguro
# reutilizar una respuesta cacheada para eso.
_MIN_WORDS_FOR_CACHE = 3


def compute_context_hash(chunks: List[RetrievedChunk]) -> str:
    """Huella determinista del contexto recuperado: cambia si cambia el
    conjunto de fragmentos o el texto de cualquiera de ellos, sin importar
    el orden en que vinieron."""
    parts = sorted(f"{c.chunk_id}:{c.text}" for c in chunks)
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


def is_cache_eligible(question: str, chunks: List[RetrievedChunk]) -> bool:
    """chunks vacío (sin información suficiente, o un saludo que no
    recuperó nada relevante) o pregunta demasiado corta -> no elegible."""
    if not chunks:
        return False
    return len(question.strip().split()) >= _MIN_WORDS_FOR_CACHE


def try_get_cached_answer(question: str, chunks: List[RetrievedChunk]) -> Optional[str]:
    """Devuelve la respuesta cacheada si hay una para este contexto exacto,
    marcando el uso. None si no es elegible o no hay coincidencia."""
    if not is_cache_eligible(question, chunks):
        return None
    context_hash = compute_context_hash(chunks)
    cached = history_service.get_cached_answer(context_hash)
    if cached is None:
        return None
    history_service.touch_cached_answer(context_hash)
    return cached["answer"]


def maybe_store_answer(question: str, chunks: List[RetrievedChunk], answer_text: str) -> None:
    """Guarda answer_text para este contexto si es elegible y no es la
    respuesta fija de "no encontré información suficiente" (no aporta
    reutilizar esa)."""
    if not is_cache_eligible(question, chunks):
        return
    if settings.NO_INFO_MESSAGE.strip() in answer_text:
        return
    context_hash = compute_context_hash(chunks)
    history_service.store_cached_answer(context_hash, question, answer_text)
