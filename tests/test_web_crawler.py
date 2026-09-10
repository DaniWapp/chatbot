"""Pruebas del rastreador de sitios web (app/rag/web_crawler.py). No
tocan la red real -- un cliente HTTP falso simula las respuestas, y
trafilatura.extract se mockea (su calidad real ya se validó a mano contra
https://www.unilibre.edu.co/cucuta/, ver el módulo)."""
from unittest.mock import patch

import pytest

from app.rag import web_crawler


# --- Unidad: normalización, filtrado, nombres de archivo -------------------


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert web_crawler.normalize_url("https://sitio.edu/cucuta/#programas") == "https://sitio.edu/cucuta"
    assert web_crawler.normalize_url("https://sitio.edu/cucuta/") == "https://sitio.edu/cucuta"
    assert web_crawler.normalize_url("https://sitio.edu") == "https://sitio.edu/"


def test_default_path_prefix_derives_from_seed_url():
    assert web_crawler.default_path_prefix("https://sitio.edu/cucuta/") == "/cucuta"
    assert web_crawler.default_path_prefix("https://sitio.edu/") == "/"


def test_is_allowed_rejects_other_domain():
    assert web_crawler.is_allowed("https://otro.com/cucuta/pagina", "sitio.edu", "/cucuta") is False


def test_is_allowed_rejects_outside_path_prefix():
    assert web_crawler.is_allowed("https://sitio.edu/otra-seccion", "sitio.edu", "/cucuta") is False


def test_is_allowed_accepts_matching_domain_and_prefix():
    assert web_crawler.is_allowed("https://sitio.edu/cucuta/facultad", "sitio.edu", "/cucuta") is True


def test_is_allowed_rejects_non_http_scheme():
    assert web_crawler.is_allowed("mailto:contacto@sitio.edu", "sitio.edu", "/cucuta") is False


def test_url_to_filename_is_stable_for_the_same_url():
    a = web_crawler.url_to_filename("https://sitio.edu/cucuta/facultad-ingenieria/")
    b = web_crawler.url_to_filename("https://sitio.edu/cucuta/facultad-ingenieria/")
    assert a == b
    assert a.endswith(".txt")


def test_url_to_filename_uses_given_extension_for_binaries():
    name = web_crawler.url_to_filename("https://sitio.edu/cucuta/resolucion.pdf", ".pdf")
    assert name.endswith(".pdf")


def test_extract_links_filters_anchors_mailto_and_javascript():
    html = """
    <a href="#seccion">ancla</a>
    <a href="mailto:contacto@sitio.edu">correo</a>
    <a href="javascript:void(0)">js</a>
    <a href="/cucuta/facultad-ingenieria/">real</a>
    """
    links = web_crawler.extract_links(html, "https://sitio.edu/cucuta/")
    assert links == ["https://sitio.edu/cucuta/facultad-ingenieria/"]


def test_extract_links_resolves_relative_urls():
    html = '<a href="otra-pagina/">rel</a>'
    links = web_crawler.extract_links(html, "https://sitio.edu/cucuta/")
    assert links == ["https://sitio.edu/cucuta/otra-pagina/"]


def test_is_placeholder_text_detects_lorem_ipsum():
    texto = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    assert web_crawler.is_placeholder_text(texto) is True


def test_is_placeholder_text_is_case_insensitive():
    assert web_crawler.is_placeholder_text("LOREM IPSUM dolor sit amet") is True


def test_is_placeholder_text_ignores_real_content():
    texto = "La Facultad de Ingeniería ofrece el programa de Ingeniería en TIC."
    assert web_crawler.is_placeholder_text(texto) is False


def test_is_placeholder_text_ignores_real_page_with_unfinished_post_embedded():
    """Caso real encontrado en producción: una página de blog con
    introducción real que, más abajo, lista la vista previa de un post
    sin redactar (puro Lorem Ipsum). La página completa sigue siendo
    útil -- no debe descartarse solo por ese fragmento embebido."""
    texto = (
        "La Navaja de Ockham es un espacio académico crítico y riguroso "
        "para reflexionar sobre el Derecho Penal y sus múltiples "
        "dimensiones, iluminando los dilemas jurídicos contemporáneos.\n"
        "Editorial #2\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    )
    assert web_crawler.is_placeholder_text(texto) is False


# --- Cliente HTTP falso, para probar crawl_site sin red real ---------------


class _FakeResponse:
    def __init__(self, text="", content=b"", status_code=200, content_type="text/html"):
        self.text = text
        self.content = content or text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeClient:
    """pages: {url: _FakeResponse}. Cualquier URL no listada devuelve 404
    (simula un enlace roto o algo fuera del sitio que igual se intentó)."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.requested_urls = []

    def get(self, url):
        self.requested_urls.append(url)
        return self.pages.get(url, _FakeResponse(status_code=404))

    def close(self):
        pass


_HOME_HTML = """
<a href="/cucuta/facultad-ingenieria/">Ingeniería</a>
<a href="https://otrosubdominio.sitio.edu/portal/">Otro subdominio</a>
<a href="https://sitio.edu/cucuta/resolucion.pdf">Resolución</a>
<a href="#programas">ancla</a>
"""
_FACULTAD_HTML = "<a href=\"/cucuta/\">Volver al inicio</a>"


def _make_pages():
    return {
        "https://sitio.edu/cucuta": _FakeResponse(text=_HOME_HTML),
        "https://sitio.edu/cucuta/facultad-ingenieria": _FakeResponse(text=_FACULTAD_HTML),
        "https://sitio.edu/cucuta/resolucion.pdf": _FakeResponse(content=b"%PDF-1.4 contenido falso"),
    }


@patch("app.rag.web_crawler.trafilatura.extract", side_effect=lambda html: f"contenido extraido de: {html[:20]}")
def test_crawl_site_follows_only_allowed_links(mock_extract):
    client = _FakeClient(_make_pages())
    pages = list(
        web_crawler.crawl_site(
            "https://sitio.edu/cucuta/", max_depth=2, max_pages=10, client=client
        )
    )
    urls = {p.url for p in pages}
    assert "https://sitio.edu/cucuta" in urls
    assert "https://sitio.edu/cucuta/facultad-ingenieria" in urls
    # El subdominio distinto nunca se pidió -- is_allowed lo descartó antes de encolarlo.
    assert not any("otrosubdominio" in u for u in client.requested_urls)


@patch("app.rag.web_crawler.trafilatura.extract", side_effect=lambda html: f"contenido extraido de: {html[:20]}")
def test_crawl_site_yields_binary_files_with_content_bytes(mock_extract):
    client = _FakeClient(_make_pages())
    pages = list(web_crawler.crawl_site("https://sitio.edu/cucuta/", max_depth=2, max_pages=10, client=client))
    pdf_page = next(p for p in pages if p.url.endswith(".pdf"))
    assert pdf_page.content_bytes == b"%PDF-1.4 contenido falso"
    assert pdf_page.text is None
    assert pdf_page.filename.endswith(".pdf")


@patch("app.rag.web_crawler.trafilatura.extract", side_effect=lambda html: f"contenido extraido de: {html[:20]}")
def test_crawl_site_respects_max_pages(mock_extract):
    client = _FakeClient(_make_pages())
    pages = list(web_crawler.crawl_site("https://sitio.edu/cucuta/", max_depth=2, max_pages=1, client=client))
    assert len(pages) == 1
    assert pages[0].url == "https://sitio.edu/cucuta"


@patch("app.rag.web_crawler.trafilatura.extract", side_effect=lambda html: f"contenido extraido de: {html[:20]}")
def test_crawl_site_respects_max_depth(mock_extract):
    """max_depth=0 -- solo la página semilla, nunca sus enlaces."""
    client = _FakeClient(_make_pages())
    pages = list(web_crawler.crawl_site("https://sitio.edu/cucuta/", max_depth=0, max_pages=10, client=client))
    assert {p.url for p in pages} == {"https://sitio.edu/cucuta"}


@patch("app.rag.web_crawler.trafilatura.extract", side_effect=lambda html: f"contenido extraido de: {html[:20]}")
def test_crawl_site_stops_when_should_stop_returns_true(mock_extract):
    client = _FakeClient(_make_pages())
    pages = list(
        web_crawler.crawl_site(
            "https://sitio.edu/cucuta/", max_depth=2, max_pages=10, should_stop=lambda: True, client=client
        )
    )
    assert pages == []


@patch("app.rag.web_crawler.trafilatura.extract", return_value=None)
def test_crawl_site_skips_pages_with_no_extractable_content(mock_extract):
    client = _FakeClient(_make_pages())
    pages = list(web_crawler.crawl_site("https://sitio.edu/cucuta/", max_depth=0, max_pages=10, client=client))
    assert pages == []


_PLANTILLA_HTML = '<a href="/cucuta/pagina-real/">real</a>'
_PAGINA_REAL_HTML = "<p>Contenido real de la facultad.</p>"


def _extract_side_effect_con_plantilla(html):
    if html == _PLANTILLA_HTML:
        return "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    return f"contenido extraido de: {html[:20]}"


@patch("app.rag.web_crawler.trafilatura.extract", side_effect=_extract_side_effect_con_plantilla)
def test_crawl_site_skips_placeholder_pages_but_still_follows_their_links(mock_extract):
    """Una página real del sitio que un editor nunca llegó a completar
    (Lorem Ipsum publicado por error) no debe indexarse -- pero sus
    enlaces sí se siguen, por si llevan a contenido real."""
    client = _FakeClient(
        {
            "https://sitio.edu/cucuta": _FakeResponse(text=_PLANTILLA_HTML),
            "https://sitio.edu/cucuta/pagina-real": _FakeResponse(text=_PAGINA_REAL_HTML),
        }
    )
    pages = list(web_crawler.crawl_site("https://sitio.edu/cucuta/", max_depth=2, max_pages=10, client=client))
    urls = {p.url for p in pages}
    assert "https://sitio.edu/cucuta" not in urls
    assert "https://sitio.edu/cucuta/pagina-real" in urls


# --- RobotsCache -------------------------------------------------------------


def test_robots_cache_blocks_disallowed_path():
    client = _FakeClient(
        {
            "https://sitio.edu/robots.txt": _FakeResponse(
                text="User-agent: *\nDisallow: /privado/", content_type="text/plain"
            )
        }
    )
    cache = web_crawler.RobotsCache(client)
    assert cache.is_allowed("https://sitio.edu/privado/algo") is False
    assert cache.is_allowed("https://sitio.edu/cucuta/publico") is True


def test_robots_cache_allows_when_robots_txt_missing():
    client = _FakeClient({})  # 404 en cualquier URL, incluida /robots.txt
    cache = web_crawler.RobotsCache(client)
    assert cache.is_allowed("https://sitio.edu/cualquier-pagina") is True
