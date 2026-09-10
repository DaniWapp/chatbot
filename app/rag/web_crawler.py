"""Rastreo de un sitio web para indexarlo igual que un documento subido:
descarga cada página permitida, extrae su contenido principal (sin menús
de navegación, pie de página ni banners -- trafilatura hace ese trabajo,
ver docs/ para la validación real contra el sitio de la universidad),
sigue los enlaces internos dentro del dominio/ruta autorizada, y también
descarga cualquier PDF/DOCX/XLSX enlazado para que pase por el mismo
extractor de documentos que ya existe (app/rag/document_loader.py).

Validado contra https://www.unilibre.edu.co/cucuta/ antes de escribir
esto: de 112 enlaces reales en la portada, solo 11 quedaban dentro de
/cucuta/ -- el resto iban a subdominios distintos, a Outlook, y hasta a
un widget de chat de un tercero. Restringir por dominio + ruta no es
opcional, es la única forma de que esto no se salga del sitio real."""
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from bs4 import BeautifulSoup

# Pausa entre peticiones -- buena práctica para no sobrecargar el
# servidor real de la institución, aunque sea su propio sitio.
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (compatible; AsistenteInstitucionalBot/1.0; indexador interno institucional)"

BINARY_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}


@dataclass
class CrawledPage:
    """Una página HTML ya extraída (text) o un archivo binario descargado
    tal cual (content_bytes), listo para pasar por el pipeline de
    ingesta existente. Exactamente uno de los dos viene con datos."""

    url: str
    filename: str
    text: Optional[str] = None
    content_bytes: Optional[bytes] = None


def normalize_url(url: str) -> str:
    """Quita el fragmento (#seccion) y la barra final, para que dos
    variaciones de la misma página no se traten como distintas páginas."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def default_path_prefix(seed_url: str) -> str:
    """Si el admin no da una ruta explícita, se restringe a la carpeta de
    la URL semilla (ej. "https://sitio.edu/cucuta/" -> "/cucuta") -- un
    valor por defecto razonable que evita salirse a todo el dominio sin
    que el admin tenga que pensarlo la primera vez."""
    path = urlparse(seed_url).path.rstrip("/")
    return path or "/"


def is_allowed(url: str, allowed_netloc: str, allowed_path_prefix: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc != allowed_netloc:
        return False
    return parsed.path.startswith(allowed_path_prefix)


def url_to_filename(url: str, extension: str = ".txt") -> str:
    """Nombre de archivo estable a partir de la URL -- la misma URL
    siempre produce el mismo nombre, así un nuevo rastreo sobreescribe la
    versión anterior de esa página (mismo criterio que subir de nuevo un
    archivo con el mismo nombre) en vez de duplicarla."""
    parsed = urlparse(url)
    slug = f"{parsed.netloc}{parsed.path}"
    slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()
    if not slug:
        slug = "index"
    return f"web-{slug[:150]}{extension}"


def extract_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        links.append(urljoin(base_url, href))
    return links


class RobotsCache:
    """Un RobotFileParser por dominio, para no volver a descargar
    robots.txt en cada página del mismo sitio. Si no hay robots.txt (o no
    se pudo leer), no bloquea el rastreo por eso -- el sitio simplemente
    no publicó reglas."""

    def __init__(self, client: httpx.Client):
        self._client = client
        self._parsers: dict = {}

    def is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._fetch_parser(origin)
        parser = self._parsers[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def _fetch_parser(self, origin: str) -> Optional[RobotFileParser]:
        try:
            response = self._client.get(urljoin(origin, "/robots.txt"))
            if response.status_code >= 400:
                return None
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            return parser
        except Exception:
            return None


def crawl_site(
    seed_url: str,
    allowed_path_prefix: Optional[str] = None,
    max_depth: int = 2,
    max_pages: int = 50,
    should_stop: Optional[Callable[[], bool]] = None,
    client: Optional[httpx.Client] = None,
) -> Iterator[CrawledPage]:
    """Recorre el sitio en anchura (BFS) desde seed_url, sin salir del
    dominio+ruta permitida, y va devolviendo cada página (o archivo
    binario) que logra extraer -- un generador, para que quien lo llame
    (ver app/services/crawl_job_service.py) pueda ir reportando progreso
    e indexando de a una sin esperar a que termine todo el rastreo.

    should_stop: función que el llamador puede usar para cancelar el
    rastreo entre una página y la siguiente."""
    allowed_netloc = urlparse(seed_url).netloc
    allowed_path_prefix = allowed_path_prefix or default_path_prefix(seed_url)
    seed_url = normalize_url(seed_url)
    should_stop = should_stop or (lambda: False)

    visited: Set[str] = set()
    queue: List[Tuple[str, int]] = [(seed_url, 0)]
    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
    )
    robots = RobotsCache(client)

    try:
        while queue and len(visited) < max_pages:
            if should_stop():
                return
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            if not robots.is_allowed(url):
                continue

            time.sleep(REQUEST_DELAY_SECONDS)
            try:
                response = client.get(url)
                response.raise_for_status()
            except Exception:
                continue

            path_lower = urlparse(url).path.lower()
            binary_ext = next((ext for ext in BINARY_EXTENSIONS if path_lower.endswith(ext)), None)
            if binary_ext:
                yield CrawledPage(url=url, filename=url_to_filename(url, binary_ext), content_bytes=response.content)
                continue

            content_type = response.headers.get("content-type", "")
            if "html" not in content_type:
                continue

            text = trafilatura.extract(response.text)
            if text and text.strip():
                yield CrawledPage(url=url, filename=url_to_filename(url), text=text)

            if depth < max_depth:
                for link in extract_links(response.text, url):
                    normalized = normalize_url(link)
                    if normalized not in visited and is_allowed(normalized, allowed_netloc, allowed_path_prefix):
                        queue.append((normalized, depth + 1))
    finally:
        if owns_client:
            client.close()
