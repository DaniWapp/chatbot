"""Pruebas del limitador de tasa de Groq (app/rag/rate_limiter.py): no
depende de Groq ni de la red. Para los casos que deben esperar, se
reemplazan time.monotonic/time.sleep por un reloj falso controlado en la
prueba, en vez de esperar los ~60s reales de la ventana."""
import time

from app.rag.rate_limiter import GroqRateLimiter


def test_acquire_does_not_block_within_limits():
    limiter = GroqRateLimiter(max_requests_per_minute=10, max_tokens_per_minute=10_000)

    start = time.monotonic()
    for _ in range(5):
        limiter.acquire(estimated_tokens=100)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5


def _install_fake_clock(monkeypatch):
    """Reemplaza time.monotonic por un reloj controlable y time.sleep por
    una función que avanza ese reloj en vez de bloquear de verdad -- así
    acquire() sigue su lógica real de reintento (incluida la poda de
    entradas viejas), solo que sin esperar segundos reales."""
    fake_time = [1_000.0]
    slept = []

    def fake_monotonic():
        return fake_time[0]

    def fake_sleep(seconds):
        slept.append(seconds)
        fake_time[0] += seconds

    monkeypatch.setattr("app.rag.rate_limiter.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.rag.rate_limiter.time.sleep", fake_sleep)
    return slept


def test_acquire_blocks_and_recovers_when_request_limit_reached(monkeypatch):
    slept = _install_fake_clock(monkeypatch)
    limiter = GroqRateLimiter(max_requests_per_minute=2, max_tokens_per_minute=10_000)

    limiter.acquire(estimated_tokens=10)
    limiter.acquire(estimated_tokens=10)
    # La tercera excede max_requests_per_minute=2: debe dormir hasta que la
    # ventana de 60s libere las dos primeras, y solo entonces continuar.
    limiter.acquire(estimated_tokens=10)

    assert len(slept) >= 1
    assert slept[0] > 0


def test_acquire_blocks_and_recovers_when_token_limit_reached(monkeypatch):
    slept = _install_fake_clock(monkeypatch)
    limiter = GroqRateLimiter(max_requests_per_minute=100, max_tokens_per_minute=100)

    limiter.acquire(estimated_tokens=90)
    # 90 + 50 > 100: no cabe todavía dentro del límite de tokens/minuto.
    limiter.acquire(estimated_tokens=50)

    assert len(slept) >= 1
    assert slept[0] > 0
