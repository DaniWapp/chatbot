"""Pruebas de división de documentos en chunks."""
from app.rag.chunker import chunk_document
from app.rag.document_loader import LoadedDocument, PageText


def test_short_text_produces_single_chunk():
    doc = LoadedDocument(filename="doc.txt", pages=[PageText(page_number=1, text="Texto corto.")])

    chunks = chunk_document(doc, chunk_size=1000, overlap=150)

    assert len(chunks) == 1
    assert chunks[0].document == "doc.txt"
    assert chunks[0].page == 1
    assert chunks[0].text == "Texto corto."


def test_long_text_is_split_into_multiple_chunks():
    long_text = "Esta es una oración de prueba. " * 200  # ~6400 caracteres
    doc = LoadedDocument(filename="largo.txt", pages=[PageText(page_number=1, text=long_text)])

    chunks = chunk_document(doc, chunk_size=1000, overlap=150)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 1000 + 50  # margen por el ajuste a límite de oración
        assert c.document == "largo.txt"


def test_chunk_ids_are_unique():
    long_text = "Frase repetida para generar varios fragmentos. " * 100
    doc = LoadedDocument(filename="doc.txt", pages=[PageText(page_number=1, text=long_text)])

    chunks = chunk_document(doc, chunk_size=500, overlap=50)
    ids = [c.chunk_id for c in chunks]

    assert len(ids) == len(set(ids))


def test_page_numbers_are_preserved_across_pages():
    doc = LoadedDocument(
        filename="doc.txt",
        pages=[
            PageText(page_number=1, text="Contenido de la página uno."),
            PageText(page_number=2, text="Contenido de la página dos."),
        ],
    )

    chunks = chunk_document(doc, chunk_size=1000, overlap=150)

    pages = {c.page for c in chunks}
    assert pages == {1, 2}
