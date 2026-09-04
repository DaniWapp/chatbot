"""Gestor de conexiones WebSocket: panel de control (una conexión por
administrador, con su propio rol y scope de dependencia) y canales por
sesión (para que un estudiante escalado reciba la respuesta del asesor en
vivo).

Las rutas de chat (/api/chat, /api/chat/stream) son funciones síncronas que
FastAPI ejecuta en un threadpool, mientras que las conexiones WebSocket
viven en el event loop asíncrono principal. Por eso el broadcast desde
chat_service (código síncrono) debe cruzar de forma segura al event loop
usando asyncio.run_coroutine_threadsafe, en vez de llamar directamente a
coroutines desde el thread del worker.
"""
import asyncio
import json
import threading
from collections import defaultdict
from typing import Dict, Optional, Set

from fastapi import WebSocket

# role='dependencia': solo le llega lo de su propia dependencia_id.
# role='general': supervisor de todo, le llega cualquier dependencia_id (ver
# _broadcast_dependencia_async). El root nunca se conecta aquí (no
# administra conversaciones).
_panel_connections: Dict[WebSocket, dict] = {}
_session_connections: Dict[str, Set[WebSocket]] = defaultdict(set)
_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def connect_panel(websocket: WebSocket, role: str, dependencia_id: Optional[int]) -> None:
    await websocket.accept()
    with _lock:
        _panel_connections[websocket] = {"role": role, "dependencia_id": dependencia_id}


def disconnect_panel(websocket: WebSocket) -> None:
    with _lock:
        _panel_connections.pop(websocket, None)


async def connect_session(session_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    with _lock:
        _session_connections[session_id].add(websocket)


def disconnect_session(session_id: str, websocket: WebSocket) -> None:
    with _lock:
        _session_connections[session_id].discard(websocket)
        if not _session_connections[session_id]:
            del _session_connections[session_id]


async def _send_to(targets: Set[WebSocket], payload: str, on_stale) -> None:
    for ws in list(targets):
        try:
            await ws.send_text(payload)
        except Exception:
            on_stale(ws)


async def _broadcast_dependencia_async(dependencia_id: Optional[int], message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False)
    with _lock:
        targets = {
            ws
            for ws, conn in _panel_connections.items()
            if conn["role"] == "general" or conn["dependencia_id"] == dependencia_id
        }
    await _send_to(targets, payload, disconnect_panel)


async def _broadcast_session_async(session_id: str, message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False)
    with _lock:
        targets = set(_session_connections.get(session_id, ()))
    await _send_to(targets, payload, lambda ws: disconnect_session(session_id, ws))


def broadcast_to_dependencia(dependencia_id: Optional[int], message: dict) -> None:
    """Llamado desde código síncrono. Notifica a los paneles de esa
    dependencia específica (o a la bandeja del general, si dependencia_id
    es None) -- y además, siempre, a todas las conexiones del rol
    'general', que supervisa cualquier dependencia en tiempo real."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast_dependencia_async(dependencia_id, message), _loop)


def broadcast_to_session(session_id: str, message: dict) -> None:
    """Llamado desde código síncrono. Notifica solo a las conexiones del
    chat del estudiante para esa sesión específica (si tiene alguna)."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast_session_async(session_id, message), _loop)
