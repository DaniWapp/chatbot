"""Limitador de tasa para las llamadas a Groq, pensado específicamente
para no exceder el plan gratuito (openai/gpt-oss-20b: 30 peticiones/minuto,
8000 tokens/minuto -- ver https://console.groq.com/docs/rate-limits).

Groq ya aplica su propio límite del lado del servidor y devuelve un error
429 si se supera; este módulo evita llegar a ese punto: antes de cada
llamada, si ya no hay margen dentro de la ventana del último minuto, la
llamada simplemente espera (sleep) su turno en vez de salir y arriesgarse
a que Groq la rechace. Es deliberadamente bloqueante (no async): todas las
rutas que llaman a Groq en este proyecto son funciones síncronas de
FastAPI, que ya corren en el threadpool del servidor -- un time.sleep()
aquí solo bloquea ese hilo de trabajo, no el event loop completo.

Es un único limitador *por proceso*, compartido por todas las funciones de
app/rag/llm.py: el límite de Groq es por cuenta/API key, no por endpoint,
así que tiene que contarse en un solo lugar sin importar si la llamada
viene del chat de un estudiante, de clasificar un escalamiento, o de la
herramienta de apoyo del asesor."""
import threading
import time
from typing import List, Tuple


class GroqRateLimiter:
    def __init__(self, max_requests_per_minute: int, max_tokens_per_minute: int):
        self._max_requests = max_requests_per_minute
        self._max_tokens = max_tokens_per_minute
        self._lock = threading.Lock()
        # Cada entrada: (marca de tiempo monotónica, tokens estimados de esa llamada).
        self._entries: List[Tuple[float, int]] = []

    def _prune(self, now: float) -> None:
        cutoff = now - 60
        self._entries = [(t, tok) for t, tok in self._entries if t > cutoff]

    def acquire(self, estimated_tokens: int) -> None:
        """Bloquea hasta que haya margen para una llamada de
        `estimated_tokens` tokens dentro de la ventana de 60s, según ambos
        límites (peticiones y tokens). Se reintenta en un bucle porque,
        tras dormir, otra llamada concurrente pudo haber tomado el cupo que
        se liberó -- se vuelve a comprobar antes de reservar el turno."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now)
                total_requests = len(self._entries)
                total_tokens = sum(tok for _, tok in self._entries)
                fits_requests = total_requests < self._max_requests
                fits_tokens = total_tokens + estimated_tokens <= self._max_tokens
                if fits_requests and fits_tokens:
                    self._entries.append((now, estimated_tokens))
                    return
                oldest = self._entries[0][0] if self._entries else now
                wait_seconds = max(60 - (now - oldest) + 0.05, 0.1)
            time.sleep(wait_seconds)
