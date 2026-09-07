"""Configuración centralizada del chatbot, cargada desde variables de entorno (.env)."""
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _get_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


class Settings:
    BASE_DIR: Path = BASE_DIR

    # Zona horaria de la institución -- usada para calcular la fecha/hora
    # "actual" que se le da al LLM (ver app/rag/llm.py::_build_system_prompt),
    # para que pueda responder preguntas relativas ("hoy", "mañana"). No usar
    # UTC directamente: cerca de la medianoche en Colombia (UTC-5) la fecha en
    # UTC ya cambió de día varias horas antes, dando el día equivocado.
    INSTITUTION_TIMEZONE: str = os.getenv("INSTITUTION_TIMEZONE", "America/Bogota")

    # --- Groq ---
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    # Extracción de texto de imágenes (afiches de eventos, etc.) al subirlas
    # como documento -- ver app/rag/llm.py::extract_text_from_image. Modelo
    # verificado en https://console.groq.com/docs/vision (puede cambiar si
    # Groq lo deprecia, igual que GROQ_MODEL).
    GROQ_VISION_MODEL: str = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
    # Groq acepta hasta 20MB por imagen en base64 (que pesa ~33% más que el
    # binario original) -- un límite más bajo aquí evita que la subida
    # llegue a intentar la llamada y falle del lado de Groq.
    GROQ_VISION_MAX_IMAGE_MB: int = _get_int("GROQ_VISION_MAX_IMAGE_MB", 14)
    # El modelo de visión tiene un límite de cuenta MUCHO más estricto que
    # GROQ_MODEL: solo 1000 tokens de salida por minuto (OTPM) en el tier
    # gratuito -- confirmado en vivo (una sola extracción con
    # max_completion_tokens=1500 ya lo superaba). Este modelo además es de
    # razonamiento: su bloque <think> también cuenta como tokens de salida,
    # así que el margen real es más chico de lo que parece.
    GROQ_VISION_MAX_COMPLETION_TOKENS: int = _get_int("GROQ_VISION_MAX_COMPLETION_TOKENS", 700)
    # Límite de tasa PROPIO para el modelo de visión -- el limitador
    # general (GROQ_MAX_REQUESTS_PER_MINUTE/GROQ_MAX_TOKENS_PER_MINUTE, más
    # abajo) está calibrado para GROQ_MODEL y no protege contra la cuota,
    # mucho más baja, del modelo de visión (ver GROQ_VISION_MAX_COMPLETION_TOKENS).
    # 900 deja margen bajo el límite real de 1000 confirmado en vivo.
    GROQ_VISION_MAX_REQUESTS_PER_MINUTE: int = _get_int("GROQ_VISION_MAX_REQUESTS_PER_MINUTE", 10)
    GROQ_VISION_MAX_TOKENS_PER_MINUTE: int = _get_int("GROQ_VISION_MAX_TOKENS_PER_MINUTE", 900)
    # Límite real del plan gratuito para openai/gpt-oss-20b: 30 peticiones/min
    # y 8000 tokens/min (ver https://console.groq.com/docs/rate-limits). Se
    # opera por debajo de eso a propósito -- deja margen para picos breves,
    # pruebas manuales, u otra fuente que use la misma cuenta sin pasar por
    # este limitador.
    GROQ_MAX_REQUESTS_PER_MINUTE: int = _get_int("GROQ_MAX_REQUESTS_PER_MINUTE", 20)
    GROQ_MAX_TOKENS_PER_MINUTE: int = _get_int("GROQ_MAX_TOKENS_PER_MINUTE", 6000)

    # --- Embeddings ---
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

    # --- RAG ---
    TOP_K: int = _get_int("TOP_K", 4)
    CHUNK_SIZE: int = _get_int("CHUNK_SIZE", 1000)
    CHUNK_OVERLAP: int = _get_int("CHUNK_OVERLAP", 150)
    # Viene desde el primer commit sin calibración documentada; se
    # verificó después contra evaluation/test_questions.json (10 preguntas
    # reales): las 7 con respuesta correcta dieron similitud 0.42-0.73
    # (todas sobre 0.35, con margen), y 2 de las 3 sin información real
    # dieron 0.16 y 0.31 (correctamente rechazadas). La tercera sin
    # información ("calendario del año 2030") dio 0.79 -- más alto que
    # varias correctas, porque el embedding mide de qué trata el texto,
    # no si el año coincide; ese caso lo resuelve una regla del prompt del
    # sistema, no este umbral. La documentación oficial de
    # sentence-transformers no recomienda un valor universal -- deja la
    # calibración al caso de uso (ver docs/conceptos-chunks-y-faiss.md).
    #
    # IMPORTANTE: desde que se descubrió el caso real "Cálculo Diferencial"
    # (ver RERANK_CANDIDATE_K abajo), este umbral solo se aplica cuando
    # RERANK_ENABLED es False. Con re-ranking activo (el caso normal),
    # retriever.py::retrieve ya NO filtra por este valor antes de
    # re-rankear -- el embedding de "la clase de calculo diferencial" dio
    # 0.27 contra su propia fila (por debajo de este umbral) y hasta menos
    # que una fila de "Álgebra Lineal" no relacionada (0.47) -- el modelo
    # de embeddings confunde estas dos frases cortas de matemáticas. El
    # cross-encoder sí las distingue perfectamente (0.34 vs. 0.01 de
    # confianza) en cuanto se le muestran ambas, así que con re-ranking
    # activo el filtro de relevancia real es RERANK_MIN_SCORE, no este.
    SIMILARITY_THRESHOLD: float = _get_float("SIMILARITY_THRESHOLD", 0.35)
    # Umbral más bajo, solo para decidir si vale la pena pedirle al LLM
    # sugerencias de reformulación cuando no hay información suficiente (ver
    # chat_service.py) -- evita llamar al LLM cuando ni siquiera hay una
    # señal débil de relación con la pregunta.
    SUGGESTION_MIN_SIMILARITY: float = _get_float("SUGGESTION_MIN_SIMILARITY", 0.10)

    # --- Re-ranking (app/rag/reranker.py) ---
    # Modelo local (sentence-transformers CrossEncoder, sin llamadas a Groq)
    # que juzga relevancia real pregunta-fragmento, no solo similitud de
    # embeddings -- ver docs/ (caso "duración"/"nivel" encontrando algo del
    # tema equivocado). reranker.py convierte el logit crudo del modelo a
    # una confianza 0-1 (sigmoide) antes de compararlo con RERANK_MIN_SCORE
    # -- calibrado con evaluation/evaluate.py: un fragmento correcto real
    # dio 0.127 de confianza, uno incorrecto dio 0.002, así que 0.3 (leído
    # como si fuera una probabilidad de un modelo bien calibrado) rechazaba
    # incluso respuestas correctas.
    RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "true").lower() == "true"
    RERANKER_MODEL: str = os.getenv("RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    # Subido de 10 a 20 tras un caso real: "Materia: Cálculo Diferencial"
    # quedaba en el puesto #11 de 50 por similitud de embeddings (el
    # modelo la confunde con "Álgebra Lineal") -- fuera de los 10
    # candidatos que se pedían antes, así que el cross-encoder (que sí la
    # habría distinguido bien) nunca llegaba a verla. Duplicar el pool
    # duplica también el tiempo de re-ranking (medido: ~770ms -> ~1565ms
    # en caliente para una pregunta) -- 20 es el mínimo verificado que
    # resuelve el caso real, no se sube más sin evidencia de que haga falta.
    RERANK_CANDIDATE_K: int = _get_int("RERANK_CANDIDATE_K", 20)
    RERANK_MIN_SCORE: float = _get_float("RERANK_MIN_SCORE", 0.05)

    # --- Historial ---
    MAX_HISTORY_TURNS: int = _get_int("MAX_HISTORY_TURNS", 3)
    HISTORY_DB_PATH: Path = BASE_DIR / os.getenv("HISTORY_DB_PATH", "history.db")
    # Respaldo periódico de history.db (todas las conversaciones): un solo
    # archivo SQLite sin respaldo se pierde entero si se corrompe o se borra
    # por error.
    HISTORY_BACKUP_DIR: Path = BASE_DIR / os.getenv("HISTORY_BACKUP_DIR", "backups")
    HISTORY_BACKUP_INTERVAL_SECONDS: int = _get_int("HISTORY_BACKUP_INTERVAL_SECONDS", 6 * 60 * 60)
    HISTORY_BACKUP_RETENTION: int = _get_int("HISTORY_BACKUP_RETENTION", 14)

    # Si una dependencia no responde (ni un solo mensaje de asesor) en este
    # tiempo desde que se le asignó una conversación, se redirige
    # automáticamente al administrador general.
    AUTO_ESCALATION_TIMEOUT_SECONDS: int = _get_int("AUTO_ESCALATION_TIMEOUT_SECONDS", 5 * 60)
    AUTO_ESCALATION_CHECK_INTERVAL_SECONDS: int = _get_int("AUTO_ESCALATION_CHECK_INTERVAL_SECONDS", 60)

    # --- Backend ---
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0")
    BACKEND_PORT: int = _get_int("BACKEND_PORT", 8000)

    # --- Seguridad ---
    # Orígenes permitidos por CORS, separados por coma. Por defecto solo el
    # propio backend (localhost) y la IP de red local típica de este proyecto.
    ALLOWED_ORIGINS: list = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",") if o.strip()
    ]
    # Límite de peticiones a /api/chat y /api/chat/stream por IP, para evitar
    # que alguien agote la cuota de Groq con peticiones repetidas.
    CHAT_RATE_LIMIT_MAX: int = _get_int("CHAT_RATE_LIMIT_MAX", 15)
    CHAT_RATE_LIMIT_WINDOW_SECONDS: int = _get_int("CHAT_RATE_LIMIT_WINDOW_SECONDS", 60)
    # Límite de intentos de /api/auth/login por IP (fuerza bruta), ahora que
    # las cuentas de administrador tienen contraseñas reales.
    LOGIN_RATE_LIMIT_MAX: int = _get_int("LOGIN_RATE_LIMIT_MAX", 10)
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = _get_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300)

    # --- Detector de hostilidad (app/services/hostility_service.py) ---
    # Cuántos mensajes hostiles seguidos (por session_id) antes de bloquear
    # esa sesión, y por cuántas horas.
    HOSTILITY_STRIKE_LIMIT: int = _get_int("HOSTILITY_STRIKE_LIMIT", 3)
    HOSTILITY_BLOCK_HOURS: float = _get_float("HOSTILITY_BLOCK_HOURS", 2.0)

    # --- Documentos ---
    DOCUMENTS_DIR: Path = BASE_DIR / os.getenv("DOCUMENTS_DIR", "documents")
    # PDF/DOCX se convierten a .txt al subirlos (ver _CONVERT_TO_TXT_EXTENSIONS
    # en app/api/routes.py) -- el original se guarda aquí, fuera de
    # DOCUMENTS_DIR, para que la ingesta siga viendo solo .txt/.xlsx.
    DOCUMENT_ORIGINALS_DIR: Path = BASE_DIR / os.getenv("DOCUMENT_ORIGINALS_DIR", "document_originals")
    VECTOR_DB_DIR: Path = BASE_DIR / os.getenv("VECTOR_DB_DIR", "vector_db")
    MAX_FILE_SIZE_MB: int = _get_int("MAX_FILE_SIZE_MB", 25)

    # Extensiones que discover_documents() reconoce como contenido indexable
    # que vive en DOCUMENTS_DIR -- las imágenes NO están aquí a propósito:
    # nunca quedan en DOCUMENTS_DIR como imagen (se convierten a .txt antes,
    # ver _IMAGE_EXTENSIONS en app/api/routes.py), así que no tiene sentido
    # que una reconstrucción completa del índice las "descubra" ahí.
    ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".xlsx"}
    COLLECTION_NAME = "facultad_ingenieria"

    # --- Institución (logo) ---
    LOGO_DIR: Path = BASE_DIR / "frontend" / "branding"
    ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
    MAX_LOGO_SIZE_MB: int = _get_int("MAX_LOGO_SIZE_MB", 5)

    NO_INFO_MESSAGE = (
        "No encontré información suficiente en la documentación disponible "
        "para responder esta pregunta."
    )


settings = Settings()
