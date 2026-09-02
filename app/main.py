"""Punto de entrada de la aplicación: API REST + servido de la interfaz web estática."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings

FRONTEND_DIR = settings.BASE_DIR / "frontend"

app = FastAPI(
    title="Chatbot Facultad de Ingeniería",
    description="Asistente RAG sobre documentos oficiales de la facultad.",
    version="1.0.0",
)

# CORS abierto: proyecto académico de uso local/demo, sin datos sensibles de usuarios.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
