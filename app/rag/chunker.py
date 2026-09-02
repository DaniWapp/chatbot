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


def chunk_document(document: LoadedDocument, chunk_size: int, overlap: int) -> List[Chunk]:
    chunks: List[Chunk] = []
    for page in document.pages:
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
