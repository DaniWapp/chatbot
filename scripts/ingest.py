#!/usr/bin/env python
"""Script de ingestión de documentos.

Uso:
    python scripts/ingest.py            # reconstruye el índice completo
    python scripts/ingest.py --no-rebuild   # agrega sin borrar lo existente

Procesa todos los PDF/DOCX/TXT dentro de la carpeta `documents/`, los divide
en chunks, genera sus embeddings y actualiza la base vectorial (FAISS).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ingest_service import run_ingestion  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta documentos hacia la base vectorial.")
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="No borrar el índice existente; solo agregar documentos nuevos.",
    )
    args = parser.parse_args()

    result = run_ingestion(rebuild=not args.no_rebuild)

    if result.errors:
        print("\nDocumentos con problemas:")
        for err in result.errors:
            print(f"  - {err}")

    if result.documents_processed == 0:
        print("\nNo se indexó ningún documento. Verifica la carpeta 'documents/'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
