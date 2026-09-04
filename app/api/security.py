"""Autenticación del panel de control (cuentas reales de administrador:
root, general o de dependencia, con sesiones de login) y limitación de
velocidad para /api/chat, /api/chat/stream y /api/auth/login."""
import dataclasses
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request

from app.config import settings
from app.services import admin_service


@dataclasses.dataclass
class AdminIdentity:
    id: int
    username: str
    display_name: str
    role: str  # 'root' | 'general' | 'dependencia'
    dependencia_id: Optional[int]


def extract_bearer_token(authorization: str) -> str:
    return authorization[7:].strip() if authorization.startswith("Bearer ") else authorization.strip()


def require_admin_session(authorization: str = Header(default="")) -> AdminIdentity:
    """Dependencia de FastAPI: exige 'Authorization: Bearer <token de
    sesión>' (obtenido en /api/auth/login) en los endpoints del panel y de
    administración. Cualquier rol pasa esta verificación; las rutas que
    necesitan un rol específico agregan require_root / require_conversation_admin
    encima."""
    identity = get_identity_for_token(extract_bearer_token(authorization))
    if identity is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada. Inicia sesión de nuevo.")
    return identity


def require_root(identity: AdminIdentity = Depends(require_admin_session)) -> AdminIdentity:
    """Para las rutas exclusivas del root (institución, dependencias,
    administradores, documentos)."""
    if identity.role != "root":
        raise HTTPException(status_code=403, detail="Esta acción requiere una cuenta root.")
    return identity


def require_conversation_admin(identity: AdminIdentity = Depends(require_admin_session)) -> AdminIdentity:
    """Para las rutas del panel de conversaciones: cualquier administrador
    salvo root, que no administra chats."""
    if identity.role == "root":
        raise HTTPException(status_code=403, detail="El root no administra conversaciones.")
    return identity


def get_identity_for_token(token: str) -> Optional[AdminIdentity]:
    """Misma resolución que require_admin_session, pero como función simple
    para usar fuera del sistema de dependencias de FastAPI -- el handshake
    de un WebSocket no puede depender de una excepción HTTP normal."""
    if not token:
        return None
    data = admin_service.get_identity_from_token(token)
    return AdminIdentity(**data) if data else None


def is_allowed_origin(origin: str) -> bool:
    return origin in settings.ALLOWED_ORIGINS


_rate_limit_lock = threading.Lock()
_rate_limit_hits: Dict[str, Deque[float]] = defaultdict(deque)
_login_rate_limit_hits: Dict[str, Deque[float]] = defaultdict(deque)


def _enforce_sliding_window(
    key: str, hits_store: Dict[str, Deque[float]], max_hits: int, window_seconds: int, detail: str
) -> None:
    now = time.monotonic()
    with _rate_limit_lock:
        hits = hits_store[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= max_hits:
            raise HTTPException(status_code=429, detail=detail)
        hits.append(now)


def enforce_chat_rate_limit(request: Request) -> None:
    """Limita cuántas veces una misma IP puede llamar a /api/chat o
    /api/chat/stream en una ventana de tiempo (CHAT_RATE_LIMIT_MAX por
    CHAT_RATE_LIMIT_WINDOW_SECONDS), para que nadie agote la cuota de Groq
    con peticiones repetidas. Se identifica por la IP del socket TCP
    (request.client.host); en un despliegue real detrás de un proxy
    reverso habría que usar X-Forwarded-For, mínimo necesario aquí."""
    client_ip = request.client.host if request.client else "unknown"
    _enforce_sliding_window(
        client_ip,
        _rate_limit_hits,
        settings.CHAT_RATE_LIMIT_MAX,
        settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
        "Demasiadas solicitudes seguidas. Espera un momento antes de volver a preguntar.",
    )


def enforce_login_rate_limit(request: Request) -> None:
    """Limita los intentos de /api/auth/login por IP, ahora que existen
    contraseñas reales que alguien podría intentar adivinar."""
    client_ip = request.client.host if request.client else "unknown"
    _enforce_sliding_window(
        client_ip,
        _login_rate_limit_hits,
        settings.LOGIN_RATE_LIMIT_MAX,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "Demasiados intentos de inicio de sesión. Espera unos minutos e intenta de nuevo.",
    )
