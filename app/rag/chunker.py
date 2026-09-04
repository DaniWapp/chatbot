"""División de documentos en fragmentos (chunks) conservando metadatos."""
import hashlib
import re
from dataclasses import dataclass
from typing import List

from app.rag.document_loader import LoadedDocument


@dataclass
class Chunk:
    chunk_id: str
    document: str
    page: int
    text: str


def _split_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Divide un texto largo en fragmentos de tamaño ~chunk_size, con overlap,
    intentando cortar en límites de oración/espacio en vez de a mitad de palabra."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    chunks: List[str] = []
    start = 0
    text_len = len(text)
    step = max(chunk_size - overlap, 1)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            # buscar el último límite de oración o espacio dentro de la ventana
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary == -1 or boundary <= start:
                boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary + 1
        fragment = text[start:end].strip()
        if fragment:
            chunks.append(fragment)
        if end >= text_len:
            break
        start += step
    return chunks


def _pack_rows(text: str) -> List[str]:
    """Cada fila de una hoja de cálculo (una línea) se convierte en su propio
    fragmento. No se agrupan varias filas en un mismo chunk: cada fila es un
    registro independiente que un usuario puede consultar de forma puntual
    (una materia, un horario, un salón). Agruparlas diluiría la búsqueda
    semántica de la misma forma que ocurría al mezclar varias preguntas de
    un FAQ en un solo fragmento."""
    return [line for line in text.split("\n") if line.strip()]


def _pack_faq_entries(text: str) -> List[str]:
    """Cada entrada de un archivo de FAQ generadas automáticamente (una
    pregunta+respuesta, separada de la siguiente por una línea en blanco --
    ver accept_faq_candidate_route) se convierte en su propio fragmento.

    Misma razón que _pack_rows: si en cambio se dejara que _split_text
    agrupara el archivo por tamaño de caracteres, conforme se acepten más
    FAQ el archivo crece y el corte de ~chunk_size caracteres termina
    mezclando varias preguntas en un mismo fragmento (diluyendo su
    similitud semántica) o incluso cortando una entrada a la mitad."""
    entries = re.split(r"\n\s*\n", text)
    return [re.sub(r"\s+", " ", e).strip() for e in entries if e.strip()]


def chunk_document(document: LoadedDocument, chunk_size: int, overlap: int) -> List[Chunk]:
    chunks: List[Chunk] = []
    for page in document.pages:
        if document.is_tabular:
            fragments = _pack_rows(page.text)
        elif document.filename.startswith("faq_generadas_"):
            fragments = _pack_faq_entries(page.text)
        else:
            fragments = _split_text(page.text, chunk_size, overlap)
        for idx, fragment in enumerate(fragments):
            raw_id = f"{document.filename}-p{page.page_number}-{idx}"
            chunk_id = hashlib.md5(raw_id.encode("utf-8")).hexdigest()[:16]
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document=document.filename,
                    page=page.page_number,
                    text=fragment,
                )
            )
    return chunks
