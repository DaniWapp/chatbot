"""Esquemas Pydantic: contratos de entrada/salida de la API."""
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Validación simple de formato (no exhaustiva RFC 5322): suficiente para
# rechazar entradas obviamente inválidas sin agregar una dependencia nueva
# como email-validator.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=2000)


class SourceCitation(BaseModel):
    document: str
    page: Optional[int] = None
    chunk_id: str
    similarity: float


class ChatMetrics(BaseModel):
    retrieval_ms: float
    generation_ms: float
    total_ms: float
    chunks_retrieved: int


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceCitation] = []
    has_sufficient_info: bool
    suggestions: List[str] = []
    metrics: ChatMetrics
    escalated: bool = False


class HealthResponse(BaseModel):
    status: str
    groq_configured: bool
    documents_indexed: int


class IngestResponse(BaseModel):
    status: str
    documents_processed: int
    chunks_created: int
    errors: List[str] = []
    # Nombre real con el que quedó guardado el archivo -- puede diferir del
    # que subió el usuario (conversión a .txt, o un consecutivo agregado
    # por una colisión de nombre, ver _next_available_txt_name).
    final_filename: Optional[str] = None


class SessionSummary(BaseModel):
    session_id: str
    last_active: str
    turn_count: int
    last_message: str
    needs_human: bool
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    escalated_at: Optional[str] = None
    dependencia_id: Optional[int] = None
    dependencia_assigned_at: Optional[str] = None
    first_response_at: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: List[SessionSummary]
    total: int
    has_more: bool
    pending_count: int


class SessionMessage(BaseModel):
    sender: str  # "student" | "assistant" | "advisor"
    message: str
    created_at: str
    message_type: str = "text"  # "text" | "checkin" | "checkin_response"


class SessionHistoryPage(BaseModel):
    messages: List[SessionMessage]
    has_more: bool
    next_cursor: Optional[str] = None


class EscalateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str) -> str:
        if not _EMAIL_RE.match(value.strip()):
            raise ValueError("Correo electrónico con formato inválido.")
        return value.strip()


class AdminReplyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class AdminAskBotRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class CheckinResponseRequest(BaseModel):
    wants_more_help: bool


class SessionStatus(BaseModel):
    needs_human: bool
    student_name: Optional[str] = None
    student_email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class LoginResponse(BaseModel):
    token: str
    role: str
    display_name: str
    dependencia_id: Optional[int] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


class DependenciaCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)


class DependenciaUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1, max_length=2000)


class DependenciaResponse(BaseModel):
    id: int
    name: str
    description: str
    created_at: str


AdminRole = Literal["root", "general", "dependencia"]


class AdminCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    role: AdminRole
    dependencia_id: Optional[int] = None

    @field_validator("username")
    @classmethod
    def validate_username_is_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value.strip()):
            raise ValueError("El usuario debe ser un correo electrónico válido.")
        return value.strip()


class AdminUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    role: Optional[AdminRole] = None
    dependencia_id: Optional[int] = None


class AdminSetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=200)


class AdminSetActiveRequest(BaseModel):
    active: bool


class AdminResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    dependencia_id: Optional[int] = None
    active: bool
    created_at: str


class InstitutionResponse(BaseModel):
    name: str
    extra_info: Optional[str] = None
    logo_url: Optional[str] = None


class DocumentInfo(BaseModel):
    filename: str
    size_bytes: int
    dependencia_id: Optional[int] = None


class DocumentRecategorizeRequest(BaseModel):
    dependencia_id: Optional[int] = None


class DocumentPreviewResponse(BaseModel):
    filename: str
    text: str
    truncated: bool


class ReassignSessionRequest(BaseModel):
    dependencia_id: Optional[int] = None


class FaqCandidateResponse(BaseModel):
    id: int
    session_id: str
    dependencia_id: Optional[int] = None
    original_question: str
    original_answer: str
    suggested_question: str
    suggested_answer: str
    status: str
    created_at: str
    decided_at: Optional[str] = None


class FaqCandidateUpdateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=5000)


class DailyCount(BaseModel):
    date: str
    count: int


class DependenciaConversationCount(BaseModel):
    dependencia_id: Optional[int] = None
    name: str
    total: int


class DashboardConversationsStats(BaseModel):
    total_escalated: int
    resolved: int
    pending_now: int
    last_7_days: int
    avg_first_response_minutes: Optional[float] = None
    avg_resolution_minutes: Optional[float] = None
    daily_trend: List[DailyCount] = []
    # Solo presente para root/general (alcance sin dependencia_id fijo).
    by_dependencia: Optional[List[DependenciaConversationCount]] = None


class RecentDocument(BaseModel):
    filename: str
    modified_at: str


class DashboardDocumentsStats(BaseModel):
    total: int
    total_size_bytes: int
    recent: List[RecentDocument] = []


class DashboardFaqStats(BaseModel):
    pending: int
    accepted: int
    rejected: int


class DashboardAdminTeamStats(BaseModel):
    dependencias_count: int
    admins_active: int
    admins_inactive: int
    admins_active_by_role: dict


class DashboardPerformanceStats(BaseModel):
    avg_retrieval_ms: Optional[float] = None
    avg_generation_ms: Optional[float] = None
    avg_total_ms: Optional[float] = None
    total_responses: int
    cache_hits: int
    cache_hit_rate: Optional[float] = None
    groq_calls_total: int
    groq_calls_failed: int
    groq_calls_last_7_days: int
    groq_calls_daily_trend: List[DailyCount] = []


class DashboardResponse(BaseModel):
    conversations: DashboardConversationsStats
    documents: DashboardDocumentsStats
    faq: DashboardFaqStats
    # Solo presentes para root.
    admin_team: Optional[DashboardAdminTeamStats] = None
    performance: Optional[DashboardPerformanceStats] = None
