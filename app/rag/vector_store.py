"""Almacenamiento y búsqueda semántica de embeddings usando FAISS (persistente en disco).

Se eligió FAISS en vez de ChromaDB porque el paquete de ChromaDB depende de
`chroma-hnswlib`, que en Windows no distribuye wheels precompilados y
requiere instalar Microsoft Visual C++ Build Tools para compilarlo desde
código fuente — una barrera pesada para un proyecto académico que debe
instalarse fácil en equipos de estudiantes. `faiss-cpu` sí distribuye wheels
precompilados para Windows, por lo que `pip install` funciona sin compilador.

Como FAISS solo almacena vectores (no metadatos), se guarda un archivo
`metadata.json` en paralelo con el documento, la página y el texto de cada
chunk, en el mismo orden que las filas del índice FAISS.
"""
import json
import re
import threading
import unicodedata
from typing import Dict, List, Optional

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from app.config import settings
from app.rag.chunker import Chunk

_lock = threading.Lock()
_index: Optional["faiss.Index"] = None
_metadata: List[Dict] = []
_loaded = False
# Índice léxico (BM25), en memoria, reconstruido cada vez que cambia
# _metadata -- ver lexical_query() y app/rag/retriever.py::retrieve() para
# por qué hace falta además de la búsqueda semántica (FAISS). No se
# persiste a disco: reconstruirlo desde _metadata toma milisegundos
# incluso con cientos de fragmentos, no vale la pena la complejidad de
# serializarlo aparte.
_bm25_index: Optional[BM25Okapi] = None


def _normalize_for_bm25(text: str) -> List[str]:
    """Minúsculas y sin acentos antes de tokenizar, para que "cálculo" y
    "calculo" (como lo escribe un estudiante real, sin tilde) coincidan
    igual."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", text.lower())


def _rebuild_bm25_index() -> None:
    global _bm25_index
    _bm25_index = BM25Okapi([_normalize_for_bm25(m["text"]) for m in _metadata]) if _metadata else None


def _index_path():
    return settings.VECTOR_DB_DIR / "index.faiss"


def _metadata_path():
    return settings.VECTOR_DB_DIR / "metadata.json"


def _ensure_loaded() -> None:
    global _index, _metadata, _loaded
    if _loaded:
        return
    settings.VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
    if _index_path().exists() and _metadata_path().exists():
        _index = faiss.read_index(str(_index_path()))
        _metadata = json.loads(_metadata_path().read_text(encoding="utf-8"))
    else:
        _index = None
        _metadata = []
    _loaded = True
    _rebuild_bm25_index()


def _persist() -> None:
    settings.VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(_index, str(_index_path()))
    _metadata_path().write_text(json.dumps(_metadata, ensure_ascii=False), encoding="utf-8")


def reset_collection() -> None:
    """Elimina el índice existente (usado al reconstruir la base vectorial desde cero)."""
    global _index, _metadata, _loaded
    with _lock:
        _index = None
        _metadata = []
        _loaded = True
        _rebuild_bm25_index()
        if _index_path().exists():
            _index_path().unlink()
        if _metadata_path().exists():
            _metadata_path().unlink()


def add_chunks(chunks: List[Chunk], embeddings: List[List[float]], dependencia_id: Optional[int] = None) -> None:
    """dependencia_id se guarda igual para todos los chunks de esta llamada
    (es un atributo del documento de origen, no del fragmento individual) --
    se usa como señal para que el LLM decida a qué dependencia redirigir una
    pregunta escalada."""
    global _index
    if not chunks:
        return
    with _lock:
        _ensure_loaded()
        vectors = np.array(embeddings, dtype="float32")
        if _index is None:
            dim = vectors.shape[1]
            # IndexFlatIP + embeddings normalizados = similitud coseno exacta.
            _index = faiss.IndexFlatIP(dim)
        _index.add(vectors)
        for c in chunks:
            _metadata.append(
                {
                    "chunk_id": c.chunk_id,
                    "document": c.document,
                    "page": c.page,
                    "text": c.text,
                    "dependencia_id": dependencia_id,
                }
            )
        _rebuild_bm25_index()
        _persist()


def remove_document(filename: str) -> None:
    """Quita del índice todos los chunks de un documento específico, sin
    tocar los demás -- para reingestar un solo archivo (subida,
    recategorización, o una FAQ aceptada) sin reconstruir todo el índice
    desde cero. Se llama siempre antes de volver a agregar ese mismo
    archivo, por si ya tenía chunks de una versión anterior de su
    contenido (evita duplicarlos).

    FAISS no borra filas de un IndexFlatIP directamente, así que se
    reconstruyen (index.reconstruct: álgebra sobre vectores ya calculados,
    NO vuelve a llamar al modelo de embeddings) los vectores que sí se
    conservan, y se arma un índice nuevo solo con esos -- barato comparado
    con rehacer los embeddings de todo el corpus."""
    global _index, _metadata
    with _lock:
        _ensure_loaded()
        if _index is None or not _metadata:
            return
        keep_indices = [i for i, m in enumerate(_metadata) if m["document"] != filename]
        if len(keep_indices) == len(_metadata):
            return  # ese documento no tenía chunks indexados

        if not keep_indices:
            _index = None
            _metadata = []
            _rebuild_bm25_index()
            if _index_path().exists():
                _index_path().unlink()
            if _metadata_path().exists():
                _metadata_path().unlink()
            return

        dim = _index.d
        kept_vectors = np.array([_index.reconstruct(i) for i in keep_indices], dtype="float32")
        new_index = faiss.IndexFlatIP(dim)
        new_index.add(kept_vectors)
        _index = new_index
        _metadata = [_metadata[i] for i in keep_indices]
        _rebuild_bm25_index()
        _persist()


def count() -> int:
    with _lock:
        _ensure_loaded()
        return _index.ntotal if _index is not None else 0


def query(embedding: List[float], top_k: int) -> List[Dict]:
    with _lock:
        _ensure_loaded()
        if _index is None or _index.ntotal == 0:
            return []
        vector = np.array([embedding], dtype="float32")
        k = min(top_k, _index.ntotal)
        similarities, indices = _index.search(vector, k)

        hits: List[Dict] = []
        for sim, idx in zip(similarities[0], indices[0]):
            if idx == -1:
                continue
            meta = _metadata[idx]
            hits.append(
                {
                    "chunk_id": meta["chunk_id"],
                    "text": meta["text"],
                    "document": meta["document"],
                    "page": meta["page"],
                    "similarity": float(sim),
                    # .get(): los índices creados antes de esta función no tienen esta clave.
                    "dependencia_id": meta.get("dependencia_id"),
                }
            )
        return hits


def lexical_query(question: str, top_k: int) -> List[Dict]:
    """Búsqueda léxica (BM25: coincidencia de palabras, no de significado)
    -- complementa query() para casos donde el embedding no distingue bien
    dos textos parecidos pero un término exacto de la pregunta sí coincide
    literalmente en el fragmento. Caso real que la motivó: para "la clase
    de calculo diferencial", el embedding de la fila "Cálculo Diferencial"
    quedaba muy por detrás de una fila de "Álgebra Lineal" no relacionada
    (el modelo de embeddings confunde estas dos frases cortas de
    matemáticas) -- BM25 la pone en el primer lugar sin ambigüedad, porque
    "calculo" y "diferencial" aparecen literalmente ahí. Ver
    app/rag/retriever.py::retrieve() para cómo se combina con query()."""
    with _lock:
        _ensure_loaded()
        if _bm25_index is None:
            return []
        scores = _bm25_index.get_scores(_normalize_for_bm25(question))
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        hits: List[Dict] = []
        for i in ranked:
            if scores[i] <= 0:
                continue
            meta = _metadata[i]
            hits.append(
                {
                    "chunk_id": meta["chunk_id"],
                    "text": meta["text"],
                    "document": meta["document"],
                    "page": meta["page"],
                    # Puntaje BM25 crudo, no una similitud coseno 0-1 --
                    # no se compara directamente contra SIMILARITY_THRESHOLD.
                    "similarity": float(scores[i]),
                    "dependencia_id": meta.get("dependencia_id"),
                }
            )
        return hits
