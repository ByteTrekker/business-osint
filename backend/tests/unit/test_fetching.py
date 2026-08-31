"""Testy warstwy pobierania.

Zero sieci i zero realnego czekania: transport jest podstawiony
(``httpx.MockTransport``), a zegar i funkcja usypiania wstrzykiwane. Dzięki temu
wykładniczy backoff, który w produkcji trwa minuty, w teście trwa mikrosekundy.
"""

from __future__ import annotations

import asyncio
import random

import httpx
import pytest

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.circuit import CircuitBreaker, CircuitState
from business_osint.etl.fetching.client import (
    ResilientClient,
    gather_resilient,
)
from business_osint.etl.fetching.errors import (
    CircuitOpenError,
    NotFoundError,
    PermanentError,
    RetryBudgetExhaustedError,
)
from business_osint.etl.fetching.policy import RetryPolicy
from business_osint.etl.fetching.profiles import (
    PROFILES,
    AccessMode,
    IncrementalMode,
    full_run_estimate_hours,
    profile_for,
    sorted_by_cost,
)
from business_osint.etl.fetching.rate_limit import RateLimiter


class FakeClock:
    """Sterowany zegar — czas płynie tylko wtedy, gdy każe mu test."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def build_client(
    handler,
    *,
    policy: RetryPolicy | None = None,
    breaker: CircuitBreaker | None = None,
    clock: FakeClock | None = None,
) -> tuple[ResilientClient, FakeClock]:
    clock = clock or FakeClock()
    return (
        ResilientClient(
            source="test",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            retry_policy=policy or RetryPolicy(max_attempts=4, initial_backoff=1.0, jitter=0.0),
            circuit_breaker=breaker,
            sleep=clock.sleep,
            rng=random.Random(0),  # noqa: S311
        ),
        clock,
    )


# --- polityka ponawiania ---------------------------------------------------


def test_backoff_grows_exponentially() -> None:
    policy = RetryPolicy(initial_backoff=1.0, multiplier=2.0, jitter=0.0)
    assert [policy.backoff_for(n) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped() -> None:
    policy = RetryPolicy(initial_backoff=1.0, multiplier=10.0, max_backoff=30.0, jitter=0.0)
    assert policy.backoff_for(10) == 30.0


def test_jitter_spreads_retries_around_the_base_delay() -> None:
    """Bez rozrzutu setki workerów wracają do rejestru w tej samej sekundzie."""
    policy = RetryPolicy(initial_backoff=10.0, multiplier=1.0, jitter=0.5)
    generator = random.Random(1)  # noqa: S311
    delays = {policy.backoff_for(1, rng=generator) for _ in range(20)}
    assert len(delays) > 1
    assert all(5.0 <= d <= 15.0 for d in delays)


def test_retry_after_header_wins_over_backoff() -> None:
    """Serwer wie lepiej, kiedy wróci — jego nagłówek jest wiążący."""
    policy = RetryPolicy(initial_backoff=1.0, jitter=0.0)
    assert policy.backoff_for(1, retry_after=42.0) == 42.0


def test_retry_after_cannot_block_a_worker_indefinitely() -> None:
    policy = RetryPolicy(max_retry_after=60.0)
    assert policy.backoff_for(1, retry_after=86_400.0) == 60.0


def test_attempt_numbering_starts_at_one() -> None:
    with pytest.raises(ValueError, match="od 1"):
        RetryPolicy().backoff_for(0)


# --- klient: ponawianie i klasyfikacja błędów ------------------------------


async def test_transient_server_error_is_retried_until_success() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"krs": "0000111111"})

    client, clock = build_client(handler)
    document = await client.get_json("https://example.invalid/x", external_id="1")

    assert document.payload == {"krs": "0000111111"}
    assert document.attempts == 3
    assert clock.slept == [1.0, 2.0]
    assert client.stats.retries == 2


async def test_timeouts_are_retried_and_never_leak_httpx_exceptions() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectTimeout("timeout", request=request)
        return httpx.Response(200, json={"ok": True})

    client, _ = build_client(handler)
    assert (await client.get_json("https://example.invalid/x", external_id="1")).payload["ok"]


async def test_retry_budget_is_finite() -> None:
    client, clock = build_client(lambda request: httpx.Response(500))

    with pytest.raises(RetryBudgetExhaustedError) as caught:
        await client.get_json("https://example.invalid/x", external_id="1")

    assert caught.value.attempts == 4
    assert len(clock.slept) == 3  # trzy przerwy między czterema próbami


async def test_not_found_is_not_retried() -> None:
    """404 to poprawna odpowiedź rejestru, nie awaria — ponawianie pali limit."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client, clock = build_client(handler)
    with pytest.raises(NotFoundError):
        await client.get_json("https://example.invalid/x", external_id="1")

    assert calls["n"] == 1
    assert clock.slept == []


async def test_client_error_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400)

    client, _ = build_client(handler)
    with pytest.raises(PermanentError):
        await client.get_json("https://example.invalid/x", external_id="1")
    assert calls["n"] == 1


async def test_rate_limit_response_honours_retry_after() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    client, clock = build_client(handler)
    await client.get_json("https://example.invalid/x", external_id="1")
    assert clock.slept == [7.0]


async def test_malformed_json_is_permanent_not_retryable() -> None:
    client, _ = build_client(lambda request: httpx.Response(200, content=b"<html>nie json"))
    with pytest.raises(PermanentError, match="JSON"):
        await client.get_json("https://example.invalid/x", external_id="1")


async def test_top_level_list_is_wrapped_so_provenance_always_has_an_object() -> None:
    client, _ = build_client(lambda request: httpx.Response(200, json=[1, 2, 3]))
    document = await client.get_json("https://example.invalid/x", external_id="1")
    assert document.payload == {"items": [1, 2, 3]}


async def test_identical_payloads_produce_identical_hashes() -> None:
    """Dedup snapshotów opiera się na sha256 — musi być niezależny od kolejności kluczy."""
    client_a, _ = build_client(lambda r: httpx.Response(200, json={"a": 1, "b": 2}))
    client_b, _ = build_client(lambda r: httpx.Response(200, json={"b": 2, "a": 1}))
    first = await client_a.get_json("https://example.invalid/x", external_id="1")
    second = await client_b.get_json("https://example.invalid/x", external_id="1")
    assert first.content_sha256 == second.content_sha256


# --- bezpiecznik -----------------------------------------------------------


def test_breaker_opens_after_threshold_and_recovers_after_timeout() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=30.0, clock=clock)

    breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()
    assert breaker.state is CircuitState.OPEN

    clock.now += 31.0
    assert breaker.allow()
    assert breaker.state is CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


def test_failed_probe_reopens_the_breaker_immediately() -> None:
    """Po nieudanej próbie rozpoznawczej nie zaczynamy liczyć błędów od zera."""
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=10.0, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now += 11.0
    assert breaker.state is CircuitState.HALF_OPEN

    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


async def test_open_breaker_stops_hammering_a_dead_registry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=60.0, clock=clock)
    client, _ = build_client(
        handler,
        policy=RetryPolicy(max_attempts=10, initial_backoff=0.0, jitter=0.0),
        breaker=breaker,
        clock=clock,
    )

    with pytest.raises(CircuitOpenError):
        await client.get_json("https://example.invalid/x", external_id="1")
    assert calls["n"] == 2  # po dwóch błędach przestajemy pukać


async def test_client_error_does_not_trip_the_breaker() -> None:
    """Nasz zły parametr to nie awaria rejestru — bezpiecznik ma zostać zamknięty."""
    breaker = CircuitBreaker(failure_threshold=1)
    client, _ = build_client(lambda r: httpx.Response(400), breaker=breaker)
    with pytest.raises(PermanentError):
        await client.get_json("https://example.invalid/x", external_id="1")
    assert breaker.state is CircuitState.CLOSED


# --- limit tempa -----------------------------------------------------------


async def test_rate_limiter_spaces_requests() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2.0, burst=1, clock=clock, sleep=clock.sleep)

    await limiter.acquire()  # pierwszy żeton jest gotowy
    assert clock.slept == []
    await limiter.acquire()  # drugi wymaga pół sekundy
    assert clock.slept == [pytest.approx(0.5)]


async def test_rate_limiter_allows_configured_burst() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, burst=3, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        await limiter.acquire()
    assert clock.slept == []


def test_rate_limiter_rejects_nonsense_configuration() -> None:
    with pytest.raises(ValueError, match="dodatnie"):
        RateLimiter(0)


# --- odporność przebiegu ---------------------------------------------------


async def test_one_failing_task_does_not_abort_the_run() -> None:
    """Sedno „żeby nie padało”: jeden martwy podmiot nie zabija importu."""

    async def ok(value: int) -> int:
        return value

    async def boom() -> int:
        raise NotFoundError("brak", source="test", url=None)

    results = await gather_resilient(
        [lambda: ok(1), boom, lambda: ok(3)],
        concurrency=2,
    )

    assert results[0] == 1
    assert isinstance(results[1], NotFoundError)
    assert results[2] == 3


async def test_gather_respects_concurrency_limit() -> None:
    active = {"now": 0, "max": 0}

    async def task() -> None:
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0)
        active["now"] -= 1

    await gather_resilient([task] * 20, concurrency=3)
    assert active["max"] <= 3


async def test_unexpected_exceptions_are_not_swallowed() -> None:
    """Błąd programisty ma wybuchnąć, a nie zamienić się w cichy wynik."""

    async def boom() -> None:
        raise ZeroDivisionError("literówka")

    with pytest.raises(ZeroDivisionError):
        await gather_resilient([boom], concurrency=1)


# --- profile źródeł --------------------------------------------------------


def test_every_source_profile_has_a_retry_policy() -> None:
    for profile in PROFILES.values():
        assert profile.retry.max_attempts >= 1
        assert profile.rate_per_second > 0


def test_per_entity_sources_are_not_configured_for_parallel_hammering() -> None:
    """Przy zapytaniach per podmiot ogranicza nas uprzejmość, nie przepustowość."""
    for profile in PROFILES.values():
        if profile.access is AccessMode.PER_ENTITY:
            assert profile.concurrency == 1
            assert profile.rate_per_second <= 1.0


def test_krs_has_no_change_feed_and_relies_on_content_hash() -> None:
    profile = profile_for(SourceKind.KRS)
    assert profile.incremental is IncrementalMode.CONTENT_HASH


def test_missing_profile_is_a_configuration_error() -> None:
    with pytest.raises(KeyError, match="brak profilu"):
        profile_for(SourceKind.MANUAL)


def test_cheapest_sources_come_first() -> None:
    order = [p.kind for p in sorted_by_cost()]
    assert order.index(SourceKind.EU_FUNDS) < order.index(SourceKind.KRS)


def test_krs_full_run_takes_days_not_hours() -> None:
    """Liczba, która wyznacza harmonogram projektu — ma być widoczna w teście."""
    hours = full_run_estimate_hours(SourceKind.KRS)
    assert 150 < hours < 250  # ~8 dni przy 1 zapytaniu na sekundę
