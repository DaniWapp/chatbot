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


def test_tabular_document_produces_one_chunk_per_row():
    """Cada fila de una hoja de cálculo debe quedar como su propio chunk,
    nunca agrupada con otras filas (evita diluir la búsqueda semántica de
    un registro específico, como pasó con el caso real del horario)."""
    rows_text = "\n".join(
        [
            "Materia: Cálculo Diferencial | Día: Lunes | Salón: A101",
            "Materia: Álgebra Lineal | Día: Martes | Salón: A102",
            "Materia: Bases de Datos | Día: Viernes | Salón: A205",
        ]
    )
    doc = LoadedDocument(
        filename="horario.xlsx",
        pages=[PageText(page_number=1, text=rows_text)],
        is_tabular=True,
    )

    chunks = chunk_document(doc, chunk_size=1000, overlap=150)

    assert len(chunks) == 3
    assert all("Materia:" in c.text and "\n" not in c.text for c in chunks)


def test_non_tabular_document_still_packs_by_character_size():
    """Confirma que el chunking normal (no tabular) no se vio afectado por
    el chunking especial de filas."""
    long_text = "Esta es una oración de prueba. " * 200
    doc = LoadedDocument(filename="largo.txt", pages=[PageText(page_number=1, text=long_text)])

    chunks = chunk_document(doc, chunk_size=1000, overlap=150)

    assert len(chunks) > 1
