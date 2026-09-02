"""Pruebas de carga y validación de documentos."""
import pytest

from app.rag.document_loader import DocumentLoadError, load_document


def test_load_txt_ok(tmp_path):
    path = tmp_path / "ejemplo.txt"
    path.write_text("Este es un documento de prueba con contenido suficiente.", encoding="utf-8")

    doc = load_document(path)

    assert doc.filename == "ejemplo.txt"
    assert len(doc.pages) == 1
    assert "contenido suficiente" in doc.pages[0].text


def test_load_empty_txt_raises(tmp_path):
    path = tmp_path / "vacio.txt"
    path.write_text("", encoding="utf-8")

    with pytest.raises(DocumentLoadError):
        load_document(path)


def test_load_unsupported_extension_raises(tmp_path):
    path = tmp_path / "imagen.png"
    path.write_bytes(b"no es texto")

    with pytest.raises(DocumentLoadError):
        load_document(path)


def test_load_corrupt_docx_raises(tmp_path):
    path = tmp_path / "corrupto.docx"
    path.write_bytes(b"esto no es un docx valido, solo bytes al azar")

    with pytest.raises(DocumentLoadError):
        load_document(path)
