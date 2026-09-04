"""Rutas de la API: /api/chat (síncrono y streaming), /api/ingest, /api/health,
/api/admin/sessions (panel de control), /api/escalate (pedir un asesor humano)."""
import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi import File, Form
from fastapi.responses import StreamingResponse

from app.api.security import (
    AdminIdentity,
    enforce_chat_rate_limit,
    enforce_login_rate_limit,
    extract_bearer_token,
    get_identity_for_token,
    is_allowed_origin,
    require_admin_session,
    require_conversation_admin,
    require_root,
)
from app.config import settings
from app.models.schemas import (
    AdminAskBotRequest,
    AdminCreateRequest,
    AdminReplyRequest,
    AdminResponse,
    AdminSetActiveRequest,
    AdminSetPasswordRequest,
    AdminUpdateRequest,
    ChangePasswordRequest,
    ChatRequest,
    ChatResponse,
    CheckinResponseRequest,
    DependenciaCreateRequest,
    DependenciaResponse,
    DependenciaUpdateRequest,
    DocumentInfo,
    DocumentRecategorizeRequest,
    EscalateRequest,
    FaqCandidateResponse,
    FaqCandidateUpdateRequest,
    HealthResponse,
    IngestResponse,
    InstitutionResponse,
    LoginRequest,
    LoginResponse,
    ReassignSessionRequest,
    SessionHistoryPage,
    SessionListResponse,
    SessionMessage,
    SessionStatus,
    SessionSummary,
)
from app.rag import llm, vector_store
from app.rag.embeddings import embed_query
from app.services import admin_service
from app.services import chat_service
from app.services import faq_service
from app.services import history as history_service
from app.services import ingest_service
from app.services import ws_manager
from app.services.ingest_service import run_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        indexed = vector_store.count()
    except Exception:
        indexed = 0
    return HealthResponse(
        status="ok",
        groq_configured=bool(settings.GROQ_API_KEY),
        documents_indexed=indexed,
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_chat_rate_limit)])
def chat(payload: ChatRequest) -> ChatResponse:
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY no configurada en el servidor. Revisa el archivo .env.",
        )
    try:
        return chat_service.answer_question(payload.session_id, payload.message)
    except Exception:
        logger.exception("Error generando respuesta para session_id=%s", payload.session_id)
        raise HTTPException(status_code=500, detail="Error generando la respuesta. Intenta de nuevo.")


@router.post("/chat/stream", dependencies=[Depends(enforce_chat_rate_limit)])
def chat_stream(payload: ChatRequest):
    """Igual que /chat pero como Server-Sent Events, para mostrar la respuesta
    apareciendo progresivamente en la interfaz (mejor percepción de velocidad)."""
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY no configurada en el servidor. Revisa el archivo .env.",
        )

    def event_generator():
        try:
            for event in chat_service.stream_answer(payload.session_id, payload.message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Error en streaming para session_id=%s", payload.session_id)
            error_event = {"type": "error", "message": "Ocurrió un error generando la respuesta."}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/institution", response_model=InstitutionResponse)
def get_institution_route() -> InstitutionResponse:
    """Nombre/logo de la institución, para que el chat del estudiante (y
    cualquier otra pantalla) lo muestre en vez de un nombre fijo en el
    HTML. Público: es información de presentación, no sensible."""
    data = admin_service.get_institution()
    logo_url = f"/static/branding/{data['logo_filename']}" if data["logo_filename"] else None
    return InstitutionResponse(name=data["name"], extra_info=data["extra_info"], logo_url=logo_url)


@router.get("/session-status/{session_id}", response_model=SessionStatus)
def get_session_status(session_id: str) -> SessionStatus:
    """Consultado por el chat del estudiante al cargar la página, para saber
    si esta sesión ya está escalada (y así reconectar el WebSocket de
    asesor y evitar volver a pedir nombre/correo)."""
    return SessionStatus(**history_service.get_session_meta(session_id))


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryPage)
def get_session_history(
    session_id: str,
    before: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> SessionHistoryPage:
    """El propio estudiante recupera su transcripción, con carga progresiva
    (para mostrarla de nuevo si recarga la página, sin traer años de
    historial de una sola vez). Sin `before` trae los últimos `limit`
    mensajes; con `before` (el cursor devuelto como `next_cursor`) trae los
    anteriores. No requiere token de admin: basta con conocer el
    session_id, igual que /escalate y /mark-solved."""
    data = history_service.get_history_page(session_id, before=before, limit=limit)
    return SessionHistoryPage(
        messages=[SessionMessage(**{k: v for k, v in m.items() if k != "_seq"}) for m in data["messages"]],
        has_more=data["has_more"],
        next_cursor=data["next_cursor"],
    )


def _broadcast_session_event(session_id: str, event: dict) -> None:
    """Envía un evento a los administradores de la dependencia actualmente
    asignada a esta sesión (o al general, si no tiene ninguna) -- el
    equivalente con scope del viejo broadcast_to_panel."""
    dependencia_id = history_service.get_session_meta(session_id)["dependencia_id"]
    ws_manager.broadcast_to_dependencia(dependencia_id, event)


def _find_similar_accepted_faqs(question: str, top_k: int = 5) -> List[str]:
    """Busca, entre los fragmentos ya indexados de archivos de FAQ
    aceptadas (faq_generadas_*.txt -- cada fragmento es una entrada
    completa "Pregunta: ... Respuesta: ...", ver app/rag/chunker.py), los
    más parecidos a una propuesta nueva. Se usa como primer filtro barato
    antes de pasarle los candidatos a llm.is_duplicate_faq -- no hace falta
    mandarle al LLM TODAS las FAQ aceptadas, solo las pocas más cercanas
    semánticamente."""
    embedding = embed_query(question)
    hits = vector_store.query(embedding, top_k=top_k)
    return [h["text"] for h in hits if h["document"].startswith("faq_generadas_") and h["similarity"] >= 0.3]


def _maybe_generate_faq_candidate(session_id: str) -> None:
    """Al resolver una conversación escalada, propone (best-effort) una
    entrada de preguntas frecuentes para que el root la revise en /root --
    ver app/rag/llm.py:generate_faq_candidate. No genera nada si nunca
    respondió un asesor de verdad (por ejemplo, se resolvió sin atención,
    o el único mensaje fue el chequeo automático "¿algo más?", que no es
    una respuesta a la pregunta), ni si la información ya existe como una
    FAQ aceptada (ver llm.is_duplicate_faq) -- evita proponer duplicados
    cuando la misma sesión (u otra) vuelve a generar una pregunta muy
    parecida a una ya publicada, solo redactada distinto."""
    history_turns = history_service.get_history(session_id)
    if not history_turns:
        return
    original_question = history_turns[-1][0]

    full_history = history_service.get_history_page(session_id, limit=1000)["messages"]
    advisor_answers = [m["message"] for m in full_history if m["sender"] == "advisor" and m["message_type"] == "text"]
    if not advisor_answers:
        return

    suggestion = llm.generate_faq_candidate(original_question, advisor_answers)
    if suggestion is None:
        return

    similar_existing = _find_similar_accepted_faqs(suggestion["question"])
    if llm.is_duplicate_faq(suggestion["question"], suggestion["answer"], similar_existing):
        return

    dependencia_id = history_service.get_session_meta(session_id)["dependencia_id"]
    faq_service.create_candidate(
        session_id=session_id,
        dependencia_id=dependencia_id,
        original_question=original_question,
        original_answer="\n\n".join(advisor_answers),
        suggested_question=suggestion["question"],
        suggested_answer=suggestion["answer"],
    )


def _classify_department_for_session(session_id: str) -> Optional[int]:
    """Best-effort: usa el LLM para decidir a qué dependencia enviar una
    conversación que se está escalando, según la última pregunta del
    estudiante y los documentos etiquetados más relevantes para ella. None
    (sin dependencias creadas, pregunta vacía, o fallo del LLM) deja la
    conversación en la bandeja del administrador general -- nunca bloquea
    el escalamiento."""
    dependencias = admin_service.list_dependencias()
    if not dependencias:
        return None

    history_turns = history_service.get_history(session_id)
    if not history_turns:
        return None
    last_question = history_turns[-1][0]

    chunks, _ = chat_service.retrieve_context(last_question)
    chunk_hints = [
        {"document": c.document, "similarity": c.similarity, "dependencia_id": c.dependencia_id} for c in chunks
    ]
    return llm.classify_department(last_question, dependencias, chunk_hints)


@router.post("/escalate")
def escalate(payload: EscalateRequest) -> dict:
    """El estudiante pide ser atendido por un humano: guarda sus datos de
    contacto, decide (best-effort, vía LLM) a qué dependencia redirigir la
    conversación, la marca como pendiente, y avisa en tiempo real al
    administrador correspondiente. De aquí en adelante el chatbot deja de
    responder en esta sesión (ver chat_service.needs_human)."""
    dependencia_id = _classify_department_for_session(payload.session_id)
    escalated_at = history_service.escalate_session(payload.session_id, payload.name, payload.email, dependencia_id)
    ws_manager.broadcast_to_dependencia(
        dependencia_id,
        {
            "type": "escalated",
            "session_id": payload.session_id,
            "student_name": payload.name,
            "student_email": payload.email,
            "escalated_at": escalated_at,
            "dependencia_id": dependencia_id,
        },
    )
    return {"status": "ok", "escalated_at": escalated_at, "dependencia_id": dependencia_id}


@router.post("/auth/login", response_model=LoginResponse, dependencies=[Depends(enforce_login_rate_limit)])
def login(payload: LoginRequest) -> LoginResponse:
    """Login de administrador (root, general o de dependencia). Mensaje de
    error genérico para no revelar si falló el usuario o la contraseña."""
    admin = admin_service.authenticate(payload.username, payload.password)
    if admin is None:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    token = admin_service.create_session(admin["id"])
    return LoginResponse(
        token=token,
        role=admin["role"],
        display_name=admin["display_name"],
        dependencia_id=admin["dependencia_id"],
    )


@router.post("/auth/logout")
def logout(authorization: str = Header(default="")) -> dict:
    admin_service.delete_session(extract_bearer_token(authorization))
    return {"status": "ok"}


@router.post("/auth/change-password", dependencies=[Depends(enforce_login_rate_limit)])
def change_password(payload: ChangePasswordRequest, identity: AdminIdentity = Depends(require_admin_session)) -> dict:
    """Cualquier administrador (incluido el root) cambia su propia
    contraseña. Invalida sus demás sesiones activas."""
    if admin_service.authenticate(identity.username, payload.current_password) is None:
        raise HTTPException(status_code=401, detail="La contraseña actual no es correcta.")
    admin_service.set_admin_password(identity.id, payload.new_password)
    return {"status": "ok"}


@router.get("/admin/sessions", response_model=SessionListResponse)
def list_sessions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=200),
    needs_human_only: bool = False,
    identity: AdminIdentity = Depends(require_conversation_admin),
) -> SessionListResponse:
    """Lista las conversaciones ESCALADAS, más recientes primero, con carga
    progresiva (offset/limit). Un administrador de dependencia solo ve las
    asignadas a la suya; el general ve TODAS (es supervisor de todo el
    sistema, no solo de lo que no se pudo clasificar). needs_human_only
    trae de una sola vez todas las pendientes dentro de ese scope, sin
    paginar, para el filtro del panel."""
    data = history_service.list_sessions(
        offset=offset,
        limit=limit,
        needs_human_only=needs_human_only,
        dependencia_scope=identity.dependencia_id,
        general_oversight=(identity.role == "general"),
    )
    return SessionListResponse(
        sessions=[SessionSummary(**s) for s in data["sessions"]],
        total=data["total"],
        has_more=data["has_more"],
        pending_count=data["pending_count"],
    )


def _ensure_admin_can_view_session(session_id: str, identity: AdminIdentity) -> None:
    """El general puede LEER cualquier conversación escalada (es supervisor
    de todo el sistema); un administrador de dependencia solo las que
    tiene asignadas. Esto es control de acceso real (no solo ocultar en la
    lista): sin esto, conocer un session_id ajeno bastaría para leerlo."""
    if identity.role == "general":
        return
    meta = history_service.get_session_meta(session_id)
    if meta["dependencia_id"] != identity.dependencia_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta conversación.")


def _ensure_admin_can_act_on_session(session_id: str, identity: AdminIdentity) -> None:
    """Responder, resolver o preguntar "¿algo más?" exige que la
    conversación esté asignada AHORA MISMO a la dependencia de este
    administrador -- a diferencia de la sola lectura, aquí el general NO
    tiene un pase libre: debe reclamarla (reasignarla hacia sí mismo, con
    dependencia_id=None) antes de poder actuar sobre una que no es suya."""
    meta = history_service.get_session_meta(session_id)
    if meta["dependencia_id"] != identity.dependencia_id:
        detail = (
            "Debes redirigir esta conversación hacia ti antes de poder responderla."
            if identity.role == "general"
            else "No tienes acceso a esta conversación."
        )
        raise HTTPException(status_code=403, detail=detail)


def _perform_reassignment(session_id: str, new_dependencia_id: Optional[int], old_dependencia_id: Optional[int]) -> str:
    """Reasigna la conversación y notifica a todos los involucrados: la
    dependencia anterior (para que desaparezca de su lista), la nueva
    (para que aparezca en la suya -- el rol 'general' ya recibe todo, ver
    ws_manager.broadcast_to_dependencia) y al propio estudiante, para que
    sepa que su solicitud se sigue gestionando. La usan tanto la
    redirección manual (reassign_session) como el auto-escalamiento por
    SLA vencido (app/main.py:_auto_escalation_loop)."""
    assigned_at = history_service.reassign_dependencia(session_id, new_dependencia_id)
    event = {
        "type": "reassigned",
        "session_id": session_id,
        "dependencia_id": new_dependencia_id,
        "dependencia_assigned_at": assigned_at,
    }
    ws_manager.broadcast_to_dependencia(old_dependencia_id, event)
    if new_dependencia_id != old_dependencia_id:
        ws_manager.broadcast_to_dependencia(new_dependencia_id, event)
    ws_manager.broadcast_to_session(
        session_id,
        {
            "type": "reassigned",
            "message": "Seguimos gestionando tu solicitud; en breve un asesor te atenderá.",
        },
    )
    return assigned_at


@router.get("/admin/sessions/{session_id}/messages", response_model=SessionHistoryPage)
def get_session_messages(
    session_id: str,
    before: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    identity: AdminIdentity = Depends(require_conversation_admin),
) -> SessionHistoryPage:
    """Transcripción de una sesión, en orden cronológico, con carga
    progresiva (antigua conversación de años se carga por páginas, no de
    una sola vez). Sin `before` trae los últimos `limit` mensajes; con
    `before` (el cursor devuelto como `next_cursor`) trae los anteriores."""
    _ensure_admin_can_view_session(session_id, identity)
    data = history_service.get_history_page(session_id, before=before, limit=limit)
    return SessionHistoryPage(
        messages=[SessionMessage(**{k: v for k, v in m.items() if k != "_seq"}) for m in data["messages"]],
        has_more=data["has_more"],
        next_cursor=data["next_cursor"],
    )


@router.post("/admin/sessions/{session_id}/reply")
def reply_to_session(
    session_id: str, payload: AdminReplyRequest, identity: AdminIdentity = Depends(require_conversation_admin)
) -> dict:
    """El asesor humano responde al estudiante desde el panel. Se guarda el
    mensaje y se transmite en tiempo real tanto al panel (otros asesores de
    la misma dependencia) como al chat del estudiante."""
    _ensure_admin_can_act_on_session(session_id, identity)
    created_at = history_service.add_admin_message(session_id, "advisor", payload.message)
    event = {
        "type": "advisor_message",
        "session_id": session_id,
        "message": payload.message,
        "created_at": created_at,
    }
    _broadcast_session_event(session_id, event)
    ws_manager.broadcast_to_session(session_id, event)
    return {"status": "ok", "created_at": created_at}


@router.post("/admin/sessions/{session_id}/ask-bot", response_model=ChatResponse)
def ask_bot_for_session(
    session_id: str, payload: AdminAskBotRequest, identity: AdminIdentity = Depends(require_conversation_admin)
) -> ChatResponse:
    """Herramienta de apoyo: el asesor le pide al chatbot un borrador de
    respuesta para una pregunta (que puede reescribir/mejorar respecto a lo
    que escribió el estudiante -- esa reescritura solo la ve el asesor). No
    se guarda nada en el historial ni se le muestra nunca al estudiante; el
    asesor decide si la usa (queda en su propio campo de respuesta para
    revisar/editar y enviar manualmente) o la descarta y escribe la
    respuesta a mano."""
    _ensure_admin_can_act_on_session(session_id, identity)
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY no configurada en el servidor. Revisa el archivo .env.",
        )
    return chat_service.draft_answer_for_admin(session_id, payload.question)


@router.post("/admin/sessions/{session_id}/ask-continue")
def ask_continue(session_id: str, identity: AdminIdentity = Depends(require_conversation_admin)) -> dict:
    """El asesor pregunta si el estudiante necesita algo más. El estudiante
    responde con dos botones (Sí/No) en vez de escribir texto; ver
    /sessions/{session_id}/checkin-response."""
    _ensure_admin_can_act_on_session(session_id, identity)
    message = "¿Te puedo ayudar con algo más?"
    created_at = history_service.add_admin_message(session_id, "advisor", message, message_type="checkin")
    event = {
        "type": "advisor_message",
        "session_id": session_id,
        "message": message,
        "message_type": "checkin",
        "created_at": created_at,
    }
    _broadcast_session_event(session_id, event)
    ws_manager.broadcast_to_session(session_id, event)
    return {"status": "ok", "created_at": created_at}


@router.post("/admin/sessions/{session_id}/resolve")
def resolve_session_as_advisor(
    session_id: str, identity: AdminIdentity = Depends(require_conversation_admin)
) -> dict:
    """El asesor marca la conversación como resuelta: el chatbot vuelve a
    responder normalmente en esta sesión."""
    _ensure_admin_can_act_on_session(session_id, identity)
    resolved_at = history_service.resolve_session(session_id, resolved_by="advisor")
    _maybe_generate_faq_candidate(session_id)
    event = {"type": "resolved", "session_id": session_id, "resolved_at": resolved_at, "resolved_by": "advisor"}
    _broadcast_session_event(session_id, event)
    ws_manager.broadcast_to_session(session_id, event)
    return {"status": "ok", "resolved_at": resolved_at}


@router.post("/admin/sessions/{session_id}/reassign")
def reassign_session(
    session_id: str, payload: ReassignSessionRequest, identity: AdminIdentity = Depends(require_conversation_admin)
) -> dict:
    """Redirige una conversación hacia otra dependencia (o hacia el
    administrador general, con dependencia_id None) -- ya sea porque el
    LLM la enrutó mal, o porque el general la está reclamando para
    atenderla él mismo. Usa el chequeo de LECTURA (_ensure_admin_can_view_session):
    el general puede reclamar cualquier conversación visible para él; un
    administrador de dependencia solo puede redirigir las que ya son
    suyas."""
    _ensure_admin_can_view_session(session_id, identity)
    old_dependencia_id = history_service.get_session_meta(session_id)["dependencia_id"]
    assigned_at = _perform_reassignment(session_id, payload.dependencia_id, old_dependencia_id)
    return {"status": "ok", "dependencia_assigned_at": assigned_at}


@router.post("/sessions/{session_id}/mark-solved")
def mark_solved_by_student(session_id: str) -> dict:
    """El propio estudiante marca su conversación completa como
    solucionada, para seguimiento y trazabilidad. Si estaba siendo atendido
    por un asesor, el chatbot vuelve a responder normalmente en esta
    sesión. No requiere el token de admin: basta con conocer el session_id
    (generado con entropía criptográfica en el navegador), igual que para
    escalar."""
    resolved_at = history_service.resolve_session(session_id, resolved_by="student")
    _maybe_generate_faq_candidate(session_id)
    event = {"type": "resolved", "session_id": session_id, "resolved_at": resolved_at, "resolved_by": "student"}
    _broadcast_session_event(session_id, event)
    return {"status": "ok", "resolved_at": resolved_at}


@router.post("/sessions/{session_id}/checkin-response")
def checkin_response(session_id: str, payload: CheckinResponseRequest) -> dict:
    """El estudiante responde al chequeo del asesor ("¿Te puedo ayudar con
    algo más?"). Si no necesita más ayuda, la conversación se marca como
    solucionada y el bot vuelve a responder normalmente en esta sesión. No
    requiere token de admin, igual que /escalate y /mark-solved."""
    reply_text = "Sí, por favor" if payload.wants_more_help else "No, gracias"
    created_at = history_service.add_admin_message(session_id, "student", reply_text, message_type="checkin_response")
    _broadcast_session_event(
        session_id,
        {
            "type": "student_message",
            "session_id": session_id,
            "message": reply_text,
            "message_type": "checkin_response",
            "created_at": created_at,
        },
    )

    resolved_at = None
    if not payload.wants_more_help:
        resolved_at = history_service.resolve_session(session_id, resolved_by="student")
        _maybe_generate_faq_candidate(session_id)
        _broadcast_session_event(
            session_id,
            {"type": "resolved", "session_id": session_id, "resolved_at": resolved_at, "resolved_by": "student"},
        )
    return {"status": "ok", "created_at": created_at, "resolved_at": resolved_at}


@router.websocket("/ws/panel")
async def ws_panel(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Canal en tiempo real para el panel de control: notifica cada turno
    nuevo, escalamiento, mensaje o resolución de cualquier conversación
    apenas ocurre. Requiere una sesión de administrador válida (?token=...,
    obtenido en /api/auth/login) y un origen permitido, ya que expone el
    contenido de las conversaciones."""
    origin = websocket.headers.get("origin", "")
    if origin and not is_allowed_origin(origin):
        await websocket.close(code=4403)
        return
    identity = get_identity_for_token(token)
    if identity is None or identity.role == "root":
        await websocket.close(code=4401)
        return

    await ws_manager.connect_panel(websocket, identity.role, identity.dependencia_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_panel(websocket)


@router.websocket("/ws/chat/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str) -> None:
    """Canal en tiempo real para el chat del estudiante: recibe la respuesta
    del asesor humano y el aviso de que la conversación fue resuelta, sin
    necesidad de recargar la página. Solo se conecta tras escalar. No exige
    token de admin (lo usa el propio estudiante), pero sí valida el origen."""
    origin = websocket.headers.get("origin", "")
    if origin and not is_allowed_origin(origin):
        await websocket.close(code=4403)
        return

    await ws_manager.connect_session(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_session(session_id, websocket)


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(require_root)])
def ingest() -> IngestResponse:
    """Reconstruye el índice vectorial a partir de los documentos en /documents.

    Pensado para uso ocasional desde una interfaz de administración simple;
    para ingestión rutinaria se recomienda `python scripts/ingest.py`.
    Requiere una cuenta root: es una operación pesada y administrativa.
    """
    result = run_ingestion(rebuild=True, log=lambda *_: None)
    return _ingest_result_to_response(result)


# --- Root: dependencias -----------------------------------------------


@router.get("/root/dependencias", response_model=List[DependenciaResponse], dependencies=[Depends(require_root)])
def list_dependencias_route() -> List[DependenciaResponse]:
    return [DependenciaResponse(**d) for d in admin_service.list_dependencias()]


@router.get(
    "/admin/dependencias", response_model=List[DependenciaResponse], dependencies=[Depends(require_conversation_admin)]
)
def list_dependencias_for_conversation_admins() -> List[DependenciaResponse]:
    """Igual que /root/dependencias, pero accesible para administradores de
    dependencia/general (no root) -- lo necesitan para elegir a quién
    redirigir manualmente una conversación mal enrutada."""
    return [DependenciaResponse(**d) for d in admin_service.list_dependencias()]


@router.post("/root/dependencias", response_model=DependenciaResponse, dependencies=[Depends(require_root)])
def create_dependencia_route(payload: DependenciaCreateRequest) -> DependenciaResponse:
    dependencia_id = admin_service.create_dependencia(payload.name, payload.description)
    return DependenciaResponse(**admin_service.get_dependencia(dependencia_id))


@router.put(
    "/root/dependencias/{dependencia_id}", response_model=DependenciaResponse, dependencies=[Depends(require_root)]
)
def update_dependencia_route(dependencia_id: int, payload: DependenciaUpdateRequest) -> DependenciaResponse:
    try:
        admin_service.update_dependencia(dependencia_id, name=payload.name, description=payload.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DependenciaResponse(**admin_service.get_dependencia(dependencia_id))


@router.delete("/root/dependencias/{dependencia_id}", dependencies=[Depends(require_root)])
def delete_dependencia_route(dependencia_id: int) -> dict:
    try:
        admin_service.delete_dependencia(dependencia_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok"}


# --- Root: administradores ----------------------------------------------


def _admin_to_response(admin: dict) -> AdminResponse:
    return AdminResponse(**{k: v for k, v in admin.items() if k != "password_hash"})


@router.get("/root/admins", response_model=List[AdminResponse], dependencies=[Depends(require_root)])
def list_admins_route() -> List[AdminResponse]:
    return [_admin_to_response(a) for a in admin_service.list_admins()]


@router.post("/root/admins", response_model=AdminResponse, dependencies=[Depends(require_root)])
def create_admin_route(payload: AdminCreateRequest) -> AdminResponse:
    try:
        admin_id = admin_service.create_admin(
            payload.username, payload.password, payload.display_name, payload.role, payload.dependencia_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _admin_to_response(admin_service.get_admin_by_id(admin_id))


@router.put("/root/admins/{admin_id}", response_model=AdminResponse, dependencies=[Depends(require_root)])
def update_admin_route(admin_id: int, payload: AdminUpdateRequest) -> AdminResponse:
    try:
        admin_service.update_admin(
            admin_id, display_name=payload.display_name, role=payload.role, dependencia_id=payload.dependencia_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _admin_to_response(admin_service.get_admin_by_id(admin_id))


@router.post("/root/admins/{admin_id}/set-password", dependencies=[Depends(require_root)])
def set_admin_password_route(admin_id: int, payload: AdminSetPasswordRequest) -> dict:
    if admin_service.get_admin_by_id(admin_id) is None:
        raise HTTPException(status_code=404, detail="No existe el administrador.")
    admin_service.set_admin_password(admin_id, payload.password)
    return {"status": "ok"}


@router.post("/root/admins/{admin_id}/set-active", dependencies=[Depends(require_root)])
def set_admin_active_route(admin_id: int, payload: AdminSetActiveRequest) -> dict:
    """"Eliminar" un administrador en este CRUD es desactivarlo, no borrar
    la fila: se preserva la trazabilidad de resolved_by/reasignaciones en
    conversaciones pasadas."""
    if admin_service.get_admin_by_id(admin_id) is None:
        raise HTTPException(status_code=404, detail="No existe el administrador.")
    admin_service.set_admin_active(admin_id, payload.active)
    return {"status": "ok"}


# --- Root: institución (nombre, logo) ------------------------------------


@router.put("/root/institution", response_model=InstitutionResponse, dependencies=[Depends(require_root)])
async def update_institution_route(
    name: str = Form(...),
    extra_info: str = Form(default=""),
    logo: Optional[UploadFile] = File(default=None),
) -> InstitutionResponse:
    logo_filename = None
    if logo is not None and logo.filename:
        ext = Path(logo.filename).suffix.lower()
        if ext not in settings.ALLOWED_LOGO_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Formato de logo no permitido: {ext}")
        content = await logo.read()
        if len(content) > settings.MAX_LOGO_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=400, detail=f"El logo supera el tamaño máximo ({settings.MAX_LOGO_SIZE_MB} MB)."
            )

        current = admin_service.get_institution()
        logo_filename = f"logo{ext}"
        if current["logo_filename"] and current["logo_filename"] != logo_filename:
            old_path = settings.LOGO_DIR / current["logo_filename"]
            if old_path.exists():
                old_path.unlink()

        settings.LOGO_DIR.mkdir(parents=True, exist_ok=True)
        (settings.LOGO_DIR / logo_filename).write_bytes(content)

    data = admin_service.update_institution(name=name, extra_info=extra_info or None, logo_filename=logo_filename)
    logo_url = f"/static/branding/{data['logo_filename']}" if data["logo_filename"] else None
    return InstitutionResponse(name=data["name"], extra_info=data["extra_info"], logo_url=logo_url)


# --- Documentos: lógica compartida entre root y el panel (general/dependencia) ---


def _ingest_result_to_response(result) -> IngestResponse:
    return IngestResponse(
        status="ok" if result.documents_processed > 0 else "sin_documentos",
        documents_processed=result.documents_processed,
        chunks_created=result.chunks_created,
        errors=result.errors,
    )


def _list_documents() -> List[DocumentInfo]:
    return [
        DocumentInfo(
            filename=path.name,
            size_bytes=path.stat().st_size,
            dependencia_id=ingest_service.get_document_dependencia(path.name),
        )
        for path in ingest_service.discover_documents()
    ]


def _upload_document(content: bytes, raw_filename: str, dependencia_id: Optional[int]) -> IngestResponse:
    """Sube un documento a DOCUMENTS_DIR, lo etiqueta con una dependencia
    (None -- general/compartido) y lo ingesta de forma incremental: solo se
    calculan embeddings de este archivo, sin tocar el resto del índice (ver
    ingest_service.ingest_single_file). Usada tanto por la ruta exclusiva
    de root como por la del panel (general/dependencia) -- el control de
    quién puede elegir qué dependencia vive en cada ruta, no aquí."""
    filename = Path(raw_filename).name  # descarta cualquier ruta de directorio en el nombre
    ext = Path(filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extensión no permitida: {ext}")

    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail=f"El archivo supera el tamaño máximo ({settings.MAX_FILE_SIZE_MB} MB)."
        )

    settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.DOCUMENTS_DIR / filename
    path.write_bytes(content)
    ingest_service.set_document_dependencia(filename, dependencia_id)

    result = ingest_service.ingest_single_file(path, dependencia_id, log=lambda *_: None)
    return _ingest_result_to_response(result)


def _recategorize_document(filename: str, dependencia_id: Optional[int]) -> IngestResponse:
    """Cambia la dependencia de un documento ya subido. El contenido no
    cambió, pero sus chunks llevan la etiqueta vieja, así que igual hay que
    reingestarlo (solo a él, no todo el índice) para que quede con la
    nueva."""
    safe_name = Path(filename).name
    path = settings.DOCUMENTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="No existe ese documento.")
    ingest_service.set_document_dependencia(safe_name, dependencia_id)
    result = ingest_service.ingest_single_file(path, dependencia_id, log=lambda *_: None)
    return _ingest_result_to_response(result)


def _delete_document(filename: str) -> None:
    safe_name = Path(filename).name
    path = settings.DOCUMENTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="No existe ese documento.")
    path.unlink()
    ingest_service.delete_document_dependencia(safe_name)
    vector_store.remove_document(safe_name)


# --- Root: documentos (sin restricción de dependencia) --------------------


@router.get("/root/documents", response_model=List[DocumentInfo], dependencies=[Depends(require_root)])
def list_documents_route() -> List[DocumentInfo]:
    return _list_documents()


@router.post("/root/documents", response_model=IngestResponse, dependencies=[Depends(require_root)])
async def upload_document_route(
    file: UploadFile = File(...),
    dependencia_id: Optional[int] = Form(default=None),
) -> IngestResponse:
    content = await file.read()
    return _upload_document(content, file.filename, dependencia_id)


@router.put("/root/documents/{filename}", response_model=IngestResponse, dependencies=[Depends(require_root)])
def recategorize_document_route(filename: str, payload: DocumentRecategorizeRequest) -> IngestResponse:
    return _recategorize_document(filename, payload.dependencia_id)


@router.delete("/root/documents/{filename}", response_model=IngestResponse, dependencies=[Depends(require_root)])
def delete_document_route(filename: str) -> IngestResponse:
    _delete_document(filename)
    return IngestResponse(status="ok", documents_processed=0, chunks_created=0, errors=[])


# --- Documentos desde /panel: general (paridad con root) y dependencia (solo lo suyo) ---


@router.get("/admin/documents", response_model=List[DocumentInfo], dependencies=[Depends(require_conversation_admin)])
def list_documents_for_panel(identity: AdminIdentity = Depends(require_conversation_admin)) -> List[DocumentInfo]:
    """El general ve todos los documentos, igual que root. Un administrador
    de dependencia solo ve los etiquetados con la suya -- no sabe siquiera
    que existen los de otras dependencias o los generales/compartidos."""
    documents = _list_documents()
    if identity.role == "dependencia":
        documents = [d for d in documents if d.dependencia_id == identity.dependencia_id]
    return documents


@router.post("/admin/documents", response_model=IngestResponse, dependencies=[Depends(require_conversation_admin)])
async def upload_document_for_panel(
    file: UploadFile = File(...),
    dependencia_id: Optional[int] = Form(default=None),
    identity: AdminIdentity = Depends(require_conversation_admin),
) -> IngestResponse:
    """Un administrador de dependencia no elige dependencia -- se ignora
    cualquier valor que mande el formulario y se fuerza la suya, para que
    nunca pueda etiquetar un documento como de otra dependencia o como
    general/compartido. El general sí puede elegir cualquiera, igual que root."""
    effective_dependencia_id = identity.dependencia_id if identity.role == "dependencia" else dependencia_id
    content = await file.read()
    return _upload_document(content, file.filename, effective_dependencia_id)


@router.put(
    "/admin/documents/{filename}", response_model=IngestResponse, dependencies=[Depends(require_conversation_admin)]
)
def recategorize_document_for_panel(
    filename: str, payload: DocumentRecategorizeRequest, identity: AdminIdentity = Depends(require_conversation_admin)
) -> IngestResponse:
    """Recategorizar (cambiar la dependencia de un documento ya subido) no
    forma parte del alcance aprobado para administradores de dependencia --
    solo el general puede hacerlo desde el panel (igual que root)."""
    if identity.role != "general":
        raise HTTPException(status_code=403, detail="Solo el administrador general puede recategorizar documentos.")
    return _recategorize_document(filename, payload.dependencia_id)


@router.delete(
    "/admin/documents/{filename}", response_model=IngestResponse, dependencies=[Depends(require_conversation_admin)]
)
def delete_document_for_panel(
    filename: str, identity: AdminIdentity = Depends(require_conversation_admin)
) -> IngestResponse:
    """El general puede eliminar cualquier documento, igual que root. Un
    administrador de dependencia solo puede eliminar los etiquetados con la
    suya."""
    if identity.role == "dependencia":
        safe_name = Path(filename).name
        if ingest_service.get_document_dependencia(safe_name) != identity.dependencia_id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este documento.")
    _delete_document(filename)
    return IngestResponse(status="ok", documents_processed=0, chunks_created=0, errors=[])


# --- Root: propuestas de preguntas frecuentes ---------------------------


def _faq_filename_for_dependencia(dependencia_id: Optional[int]) -> str:
    """Un archivo por dependencia (y uno para el general/sin clasificar),
    para que la propuesta aceptada herede la misma etiqueta que tenía la
    conversación de origen -- document_dependencias etiqueta por archivo
    completo, no por entrada dentro de él."""
    if dependencia_id is None:
        return "faq_generadas_general.txt"
    return f"faq_generadas_dependencia_{dependencia_id}.txt"


@router.get(
    "/root/faq-candidates", response_model=List[FaqCandidateResponse], dependencies=[Depends(require_root)]
)
def list_faq_candidates_route(status: Optional[str] = "pending") -> List[FaqCandidateResponse]:
    return [FaqCandidateResponse(**c) for c in faq_service.list_candidates(status=status)]


@router.put(
    "/root/faq-candidates/{candidate_id}",
    response_model=FaqCandidateResponse,
    dependencies=[Depends(require_root)],
)
def update_faq_candidate_route(candidate_id: int, payload: FaqCandidateUpdateRequest) -> FaqCandidateResponse:
    if faq_service.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="No existe esa propuesta.")
    faq_service.update_candidate_text(candidate_id, payload.question, payload.answer)
    return FaqCandidateResponse(**faq_service.get_candidate(candidate_id))


@router.post("/root/faq-candidates/{candidate_id}/reject", dependencies=[Depends(require_root)])
def reject_faq_candidate_route(candidate_id: int) -> dict:
    if faq_service.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="No existe esa propuesta.")
    faq_service.mark_decided(candidate_id, "rejected")
    return {"status": "ok"}


@router.post(
    "/root/faq-candidates/{candidate_id}/accept",
    response_model=IngestResponse,
    dependencies=[Depends(require_root)],
)
def accept_faq_candidate_route(candidate_id: int) -> IngestResponse:
    """Agrega la pregunta/respuesta (ya editadas si el root las cambió) al
    archivo de FAQ de su dependencia (o al general), etiqueta ese archivo
    igual, y reingesta -- mismo pipeline que subir un documento manualmente."""
    candidate = faq_service.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="No existe esa propuesta.")
    if candidate["status"] != "pending":
        raise HTTPException(status_code=409, detail="Esta propuesta ya fue decidida.")

    filename = _faq_filename_for_dependencia(candidate["dependencia_id"])
    settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = f"Pregunta: {candidate['suggested_question']}\nRespuesta: {candidate['suggested_answer']}\n\n"
    with open(settings.DOCUMENTS_DIR / filename, "a", encoding="utf-8") as f:
        f.write(entry)
    ingest_service.set_document_dependencia(filename, candidate["dependencia_id"])

    faq_service.mark_decided(candidate_id, "accepted")

    result = ingest_service.ingest_single_file(
        settings.DOCUMENTS_DIR / filename, candidate["dependencia_id"], log=lambda *_: None
    )
    return _ingest_result_to_response(result)
