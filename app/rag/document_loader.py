"""Carga y extracción de texto de documentos (PDF, DOCX, TXT).

Cada documento se descompone en una lista de "páginas" de texto para poder
conservar la referencia de página en los metadatos de cada chunk. Los TXT y
DOCX no tienen paginación real, así que se tratan como una única "página".
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.config import settings


class DocumentLoadError(Exception):
    """Se lanza cuando un documento no puede leerse (corrupto, formato inválido, etc.)."""


@dataclass
class PageText:
    page_number: int  # 1-indexado; None-like sentinel = 1 para formatos sin páginas
    text: str


@dataclass
class LoadedDocument:
    filename: str
    pages: List[PageText]


def validate_file(path: Path) -> None:
    if path.suffix.lower() not in settings.ALLOWED_EXTENSIONS:
        raise DocumentLoadError(
            f"Extensión no soportada: {path.suffix}. Permitidas: {settings.ALLOWED_EXTENSIONS}"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise DocumentLoadError(
            f"Archivo demasiado grande ({size_mb:.1f}MB). Límite: {settings.MAX_FILE_SIZE_MB}MB"
        )
    if path.stat().st_size == 0:
        raise DocumentLoadError("El archivo está vacío.")


def _load_pdf(path: Path) -> List[PageText]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise DocumentLoadError(f"No se pudo abrir el PDF (¿está corrupto?): {exc}") from exc

    pages: List[PageText] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            pages.append(PageText(page_number=i, text=text))

    if not pages:
        raise DocumentLoadError("El PDF no contiene texto extraíble (¿está escaneado como imagen?).")
    return pages


def _load_docx(path: Path) -> List[PageText]:
    try:
        doc = DocxDocument(str(path))
    except Exception as exc:
        raise DocumentLoadError(f"No se pudo abrir el DOCX (¿está corrupto?): {exc}") from exc

    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not text.strip():
        raise DocumentLoadError("El DOCX no contiene texto.")
    return [PageText(page_number=1, text=text)]


def _load_txt(path: Path) -> List[PageText]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="latin-1")
        except Exception as exc:
            raise DocumentLoadError(f"No se pudo leer el TXT: {exc}") from exc
    except Exception as exc:
        raise DocumentLoadError(f"No se pudo leer el TXT: {exc}") from exc

    if not text.strip():
        raise DocumentLoadError("El TXT está vacío.")
    return [PageText(page_number=1, text=text)]


def load_document(path: Path) -> LoadedDocument:
    """Carga un documento y devuelve su texto dividido por página.

    Lanza DocumentLoadError con un mensaje claro si el archivo no es válido
    o está corrupto, para que el proceso de ingestión pueda omitirlo sin
    detener el resto del lote.
    """
    validate_file(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = _load_pdf(path)
    elif suffix == ".docx":
        pages = _load_docx(path)
    elif suffix == ".txt":
        pages = _load_txt(path)
    else:
        raise DocumentLoadError(f"Extensión no soportada: {suffix}")

    return LoadedDocument(filename=path.name, pages=pages)
