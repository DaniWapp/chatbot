"""Esquemas Pydantic: contratos de entrada/salida de la API."""
from typing import List, Optional

from pydantic import BaseModel, Field


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
    metrics: ChatMetrics


class HealthResponse(BaseModel):
    status: str
    groq_configured: bool
    documents_indexed: int


class IngestResponse(BaseModel):
    status: str
    documents_processed: int
    chunks_created: int
    errors: List[str] = []
